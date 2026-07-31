import os
import speech_recognition as sr
import csv
import time
import re
import edge_tts
import asyncio
import pygame
import threading
import difflib
import fitz  # Voor PDF naar afbeelding conversie
from pathlib import Path

from kivy.config import Config

# --- KIVY OPTIMALISATIE & FULLSCREEN ---
Config.set('graphics', 'multisamples', '0')
Config.set('graphics', 'always_on_top', '0')
Config.set('graphics', 'maxfps', '60')
Config.set('graphics', 'fullscreen', 'auto')
Config.set('kivy', 'log_level', 'error')

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.clock import Clock
from kivy.utils import get_color_from_hex
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.graphics import Color, Rectangle
from kivy.animation import Animation
from kivy.properties import NumericProperty
from kivy.utils import platform

if platform == 'android':
    from android.permissions import request_permissions, Permission
    # Vraag direct bij opstarten toestemming voor microfoon en opslag
    request_permissions([
        Permission.RECORD_AUDIO,
        Permission.READ_EXTERNAL_STORAGE,
        Permission.WRITE_EXTERNAL_STORAGE
    ])
# --- MAPSTRUCTUUR ---
ASSETS_DIR = "assets"
PICTO_DIR = "pictogrammen"
MSDS_DIR = "msds"
TEMP_PDF_DIR = "temp_pdf"

for folder in [ASSETS_DIR, PICTO_DIR, MSDS_DIR, TEMP_PDF_DIR]:
    if not os.path.exists(folder): os.makedirs(folder)

BG_STANDBY = '#F5EFDB'
KLEUR_TEKST_DONKER = '#273f53'
KLEUR_LUISTEREN = '#2ECC71'
KLEUR_VRAAG = '#F1C40F'
KLEUR_NOOD = '#E74C3C'
KLEUR_KEUZE = '#3498DB'
INTRO_DUUR = 2.5
KLEUR_MUTE = '#FFFFFF'
KLEUR_STOP = '#E74C3C'
KLEUR_TEKST_WIT = '#E74C3C'

Window.clearcolor = get_color_from_hex(BG_STANDBY)

try:
    LabelBase.register(name='MijnFont', fn_regular=os.path.join(ASSETS_DIR, 'Monas-BLBW8.ttf'))
    GEBRUIK_FONT = 'MijnFont'
except:
    GEBRUIK_FONT = 'Roboto'


class ProgressWidget(Widget):
    value = NumericProperty(900)
    max = NumericProperty(900)


class ChemieApp(App):
    def build(self):
        Window.fullscreen = 'auto'
        self.nood_actief = False
        self.systeem_bezet = False  # Voorkomt dat de loop de UI reset
        self.pdf_is_pauze = False
        self.gekozen_locatie = None
        self.keuze_event = threading.Event()
        self.huidige_pdf_anim = None
        self.huidige_pdf_index = 0
        self.totaal_pdf_paginas = 0
        self.scroll_snelheid_standaard = 40
        self.lab_database = {}
        self.timer_seconds = 900  # Standaard 15 minuten
        self.timer_event = None  # Houdt de actieve klok-loop bij

        try:
            pygame.mixer.pre_init(44100, -16, 2, 2048)
            pygame.mixer.init()
            self.alarm_sound = pygame.mixer.Sound(os.path.join(ASSETS_DIR, "alarm.wav"))
            self.ping_sound = pygame.mixer.Sound(os.path.join(ASSETS_DIR, "ping.wav"))
            intro_p = os.path.join(ASSETS_DIR, "intro_audio.mp3")
            self.intro_audio = pygame.mixer.Sound(intro_p) if os.path.exists(intro_p) else None
        except:
            self.alarm_sound = self.ping_sound = self.intro_audio = None

        self.root = FloatLayout()
        with self.root.canvas.before:
            self.bg_color = Color(rgba=get_color_from_hex(BG_STANDBY))
            self.bg_rect = Rectangle(size=Window.size, pos=(0, 0))
        self.root.bind(size=self._update_rect, pos=self._update_rect)

        self.ui = BoxLayout(orientation='vertical', padding=50, spacing=20, size_hint=(1, 1))
        self.pic_layout = BoxLayout(orientation='horizontal', size_hint=(1, 0.001), spacing=20)
        self.centraal_label = Label(text="CHEMI", font_name=GEBRUIK_FONT, font_size='100sp', opacity=0, bold=True,
                                    color=get_color_from_hex(KLEUR_TEKST_DONKER))
        self.status_log = Label(text=" ", font_size='14sp', size_hint=(1, 0.1),
                                color=get_color_from_hex('#7f8c8d'), halign='center')

        self.progress = ProgressWidget(size_hint=(0.6, 0.01), pos_hint={'center_x': 0.5, 'y': 0.15}, opacity=0)
        with self.progress.canvas:
            self.bg_bar_color = Color(rgba=get_color_from_hex('#BDC3C7'))
            self.bar_bg_rect = Rectangle(pos=self.progress.pos, size=self.progress.size)
            self.fill_bar_color = Color(rgba=get_color_from_hex('#FFFFFF'))
            self.bar_fill_rect = Rectangle(pos=self.progress.pos, size=self.progress.size)

        def update_progress_rects(obj, *args):
            self.bar_bg_rect.pos = obj.pos
            self.bar_bg_rect.size = obj.size
            vul_breedte = (obj.value / obj.max) * obj.width if obj.max > 0 else 0
            self.bar_fill_rect.pos = obj.pos
            self.bar_fill_rect.size = (max(0, vul_breedte), obj.height)

        self.progress.bind(pos=update_progress_rects, size=update_progress_rects, value=update_progress_rects)

        self.ui.add_widget(self.pic_layout)
        self.ui.add_widget(self.centraal_label)
        self.ui.add_widget(self.status_log)
        self.root.add_widget(self.ui)
        self.root.add_widget(self.progress)

        # --- LOCATIE KEUZE KNOPPEN ---
        self.btn_layout_locatie = BoxLayout(orientation='horizontal', size_hint=(None, None), size=(500, 75),
                                            pos_hint={'center_x': 0.5, 'y': -0.3}, spacing=40, opacity=0)
        btn_style = {'background_normal': '', 'font_size': '22sp', 'bold': True}
        self.btn_lab = Button(text="LABORATORIUM", background_color=get_color_from_hex(KLEUR_TEKST_DONKER), **btn_style)
        self.btn_fabriek = Button(text="FABRIEK", background_color=get_color_from_hex(KLEUR_TEKST_DONKER), **btn_style)

        self.btn_lab.bind(on_release=lambda x: self.set_locatie("lab"))
        self.btn_fabriek.bind(on_release=lambda x: self.set_locatie("fabriek"))

        self.btn_layout_locatie.add_widget(self.btn_lab)
        self.btn_layout_locatie.add_widget(self.btn_fabriek)
        self.root.add_widget(self.btn_layout_locatie)

        self.btn_nood_stop = Button(text="STOP NOODPROCEDURE", size_hint=(None, None), size=(400, 100),
                                    pos_hint={'center_x': 0.5, 'y': -0.2}, background_normal='',
                                    background_color=(1, 1, 1, 1), color=get_color_from_hex(KLEUR_NOOD), bold=True,
                                    font_size='24sp', opacity=0)
        self.btn_nood_stop.bind(on_release=self.stop_noodprocedure)
        self.root.add_widget(self.btn_nood_stop)

        self.btn_alarm_mute = Button(
            text="ALARM\nDEMPEN",
            size_hint=(None, None),
            size=(220, 100),
            pos_hint={'center_x': 0.3, 'y': -0.2},
            background_normal='',
            background_color=get_color_from_hex(KLEUR_MUTE),
            # HIER PAS JE DE LETTERKLEUR AAN:
            color=get_color_from_hex(KLEUR_TEKST_WIT),
            bold=True,
            halign='center',
            font_size='20sp',
            opacity=0
        )
        self.btn_alarm_mute.bind(on_release=self.mute_alarm)
        self.root.add_widget(self.btn_alarm_mute)

        # Pas de positie van je bestaande STOP knop een beetje aan (iets naar rechts)
        # zodat ze niet over elkaar heen vallen:
        self.btn_nood_stop.pos_hint = {'center_x': 0.7, 'y': -0.2}

        # --- VERBETERDE SCROLLVIEW CREATIE ---
        self.pdf_scroll_view = ScrollView(size_hint=(0.9, 0.80), pos_hint={'center_x': 0.5, 'center_y': 0.58},
                                          do_scroll_x=False, do_scroll_y=True, opacity=0)

        # We binden direct aan de 'on_scroll_start' van de ScrollView zelf
        self.pdf_scroll_view.bind(on_scroll_start=self.handmatige_scroll_detectie)

        self.pdf_overlay = Image(size_hint_y=None, allow_stretch=True, keep_ratio=True)
        self.pdf_scroll_view.add_widget(self.pdf_overlay)
        self.root.add_widget(self.pdf_scroll_view)
        self.pdf_controls = BoxLayout(orientation='horizontal', size_hint=(None, None), size=(550, 110),
                                      pos_hint={'center_x': 0.52, 'y': -0.2}, padding=10, spacing=20)
        self.btn_prev = Button(background_normal=os.path.join(ASSETS_DIR, 'vorige_knop.png'), size_hint=(None, None),
                               size=(100, 100))
        self.btn_prev.bind(on_release=lambda x: self.wissel_pagina(-1))
        self.btn_pauze = Button(background_normal=os.path.join(ASSETS_DIR, 'pauze_knop.png'), size_hint=(None, None),
                                size=(100, 100))
        self.btn_pauze.bind(on_release=self.toggle_pauze)
        self.btn_next = Button(background_normal=os.path.join(ASSETS_DIR, 'volgende_knop.png'), size_hint=(None, None),
                               size=(100, 100))
        self.btn_next.bind(on_release=lambda x: self.wissel_pagina(1))
        self.btn_stop = Button(background_normal=os.path.join(ASSETS_DIR, 'stop_knop.png'), size_hint=(None, None),
                               size=(100, 100))
        self.btn_stop.bind(on_release=self.sluit_pdf)

        for widget in [self.btn_prev, self.btn_pauze, self.btn_next, self.btn_stop]:
            self.pdf_controls.add_widget(widget)
        self.root.add_widget(self.pdf_controls)

        Clock.schedule_once(self.start_intro_sequentie, 0.5)
        return self.root

    def start_nood_timer(self, info, minuten=15):
        self.nood_actief = True
        self.systeem_bezet = True
        self.timer_seconds = minuten * 60

        # UI direct instellen (Nog voor de eerste tick)
        self.centraal_label.halign = 'center'  # Forceer midden-uitlijning
        self.update_ui(f"NOODGEVAL\n{minuten}:00", "#E74C3C", "#FFFFFF", info['pictogram'])

        self.progress.max = self.timer_seconds
        self.progress.value = self.timer_seconds
        self.progress.opacity = 1

        if self.alarm_sound: self.alarm_sound.play(loops=-1)

        Animation(pos_hint={'center_x': 0.5, 'y': 0.05}, opacity=1, duration=0.5).start(self.btn_nood_stop)

        if self.timer_event: self.timer_event.cancel()
        self.timer_event = Clock.schedule_interval(lambda dt: self._timer_tick(info), 1.0)

        tekst = info['n_ogen'] if info['n_ogen'] else f"Begin direct met spoelen voor {minuten} minuten."
        threading.Thread(target=self.assistent_spreekt, args=(tekst,), daemon=True).start()

        Animation(pos_hint={'center_x': 0.35, 'y': 0.05}, opacity=1, duration=0.5).start(self.btn_alarm_mute)
        Animation(pos_hint={'center_x': 0.7, 'y': 0.05}, opacity=1, duration=0.5).start(self.btn_nood_stop)

        # Reset de mute knop status voor het geval hij vorige keer gebruikt is
        self.btn_alarm_mute.disabled = False
        self.btn_alarm_mute.text = "ALARM UIT"

    def _timer_tick(self, info):
        if not self.nood_actief: return False

        self.timer_seconds -= 1
        self.progress.value = self.timer_seconds

        mins, secs = divmod(self.timer_seconds, 60)

        # Gebruik een f-string met een nieuwe regel (\n)
        # Door halign='center' in de build of start_nood_timer te zetten, blijft dit in het midden.
        self.centraal_label.text = f"NOODGEVAL\n{mins:02d}:{secs:02d}"

        if self.timer_seconds <= 0:
            self.stop_timer_voltooid()
            return False
        return True

    def stop_timer_voltooid(self):
        """Actie wanneer de 15 minuten voorbij zijn."""
        if self.alarm_sound: self.alarm_sound.stop()
        self.update_ui("KLAAR", "#27AE60", "#FFFFFF")  # Scherm wordt groen
        threading.Thread(target=self.assistent_spreekt, args=("De spoeltijd is voorbij. Controleer het oog."),
                         daemon=True).start()

    def set_locatie(self, loc):
        print(f"DEBUG: Er is geklikt op {loc}")  # Testregel
        self.gekozen_locatie = loc
        self.keuze_event.set()

    def vraag_locatie_en_antwoord(self, info):
        self.systeem_bezet = True
        self.gekozen_locatie = None
        self.keuze_event.clear()

        try:
            # 1. Toon de knoppen (voor als men wil klikken)
            Clock.schedule_once(lambda dt: self.update_ui("KIES LOCATIE", KLEUR_KEUZE, "#FFFFFF", info['pictogram']))
            Clock.schedule_once(
                lambda dt: Animation(pos_hint={'center_x': 0.5, 'y': 0.1}, opacity=1, duration=0.5).start(
                    self.btn_layout_locatie))

            # 2. Stel de vraag
            self.assistent_spreekt("Is dit voor het laboratorium of de fabriek?")
            if self.ping_sound: self.ping_sound.play()

            # 3. Start een korte luister-sessie voor de keuze
            keuze_via_stem = None
            try:
                with sr.Microphone() as source:
                    # Kortere timeout omdat we specifiek op 1 woord wachten
                    audio_keuze = self.recognizer.listen(source, timeout=5, phrase_time_limit=3)
                    keuze_via_stem = self.recognizer.recognize_google(audio_keuze, language="nl-NL").lower()
            except:
                pass  # Geen spraak gehoord, we vallen terug op de knoppen

            # 4. Verwerk de stem-input (indien aanwezig)
            if keuze_via_stem:
                if "lab" in keuze_via_stem or "laboratorium" in keuze_via_stem:
                    self.gekozen_locatie = "lab"
                    self.keuze_event.set()
                elif "fabriek" in keuze_via_stem or "hal" in keuze_via_stem:
                    self.gekozen_locatie = "fabriek"
                    self.keuze_event.set()

            # 5. Wacht op klik als er GEEN stem-input was (max 10 sec extra)
            start_wachten = time.time()
            while not self.keuze_event.is_set() and (time.time() - start_wachten) < 10:
                time.sleep(0.1)

            # 6. Verberg knoppen
            Clock.schedule_once(
                lambda dt: Animation(pos_hint={'center_x': 0.5, 'y': -0.3}, opacity=0, duration=0.3).start(
                    self.btn_layout_locatie))

            # 7. Resultaat bepalen & uitspreken
            loc = self.gekozen_locatie if self.gekozen_locatie else "lab"
            pbm_tekst = info['pbm_lab'] if loc == "lab" else info['pbm_fabriek']
            pbm_pics = info.get('pbm_pic_lab', "") if loc == "lab" else info.get('pbm_pic_fabriek', "")

            Clock.schedule_once(lambda dt: self.update_ui(info['naam'], KLEUR_LUISTEREN, "#FFFFFF", pbm_pics))
            self.assistent_spreekt(f"De PBM's voor het {loc} zijn: {pbm_tekst}")

            time.sleep(3.0)

        finally:
            self.systeem_bezet = False
            Clock.schedule_once(lambda dt: self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER))

    def assistent_spreekt(self, tekst):
        try:
            bestandsnaam = f"spraak_{int(time.time())}.mp3"
            asyncio.run(edge_tts.Communicate(tekst, "nl-NL-FennaNeural").save(bestandsnaam))

            pygame.mixer.music.load(bestandsnaam)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.05)

            pygame.mixer.music.unload()
            if os.path.exists(bestandsnaam):
                try: os.remove(bestandsnaam)
                except: pass
        except Exception as e:
            print(f"Spraakfout: {e}")

    # --- NOODGEVAL & PDF FUNCTIES ---
    def log_noodgeval(self, stof):
        with open('noodlog.csv', 'a', encoding='utf-8') as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')},{stof}\n")

    def update_countdown(self, dt):
        if not self.nood_actief: return False
        self.progress.value -= 1
        return self.progress.value > 0

    def forceer_nood_ogen_zoutzuur(self, info):
        self.nood_actief = True
        self.log_noodgeval(info['naam'])
        self.progress.opacity = 1
        self.progress.value = 900
        Clock.schedule_interval(self.update_countdown, 1.0)
        Animation(pos_hint={'center_x': 0.5, 'y': 0.05}, opacity=1, duration=0.5).start(self.btn_nood_stop)
        threading.Thread(target=self._voer_nood_uit, args=(info,), daemon=True).start()

    def _voer_nood_uit(self, info):
        if self.alarm_sound: self.alarm_sound.play(loops=-1)
        self.update_ui("NOODGEVAL", KLEUR_NOOD, "#FFFFFF", info['pictogram'])
        bericht = info['n_ogen'] if info['n_ogen'] else "Geen instructies beschikbaar."
        self.assistent_spreekt(bericht)

    def toon_pdf_in_app(self, pdf_pad):
        self.pdf_is_pauze = False
        self.systeem_bezet = True

        # --- VOEG DEZE REGEL TOE: Zet achtergrond naar wit of standby-kleur ---
        self.update_ui("PDF WEERGAVE", "#F5EFDB", KLEUR_TEKST_DONKER)

        # Bind de scroll_y aan een functie die kijkt of de gebruiker handmatig scrollt
        self.pdf_scroll_view.bind(scroll_y=self.check_handmatig_scrollen)

        def verwerk_pdf():
            try:
                doc = fitz.open(pdf_pad)
                self.totaal_pdf_paginas = len(doc)
                zoom = fitz.Matrix(1.5, 1.5)
                for i in range(self.totaal_pdf_paginas):
                    doc.load_page(i).get_pixmap(matrix=zoom).save(os.path.join(TEMP_PDF_DIR, f"page_{i}.png"))
                doc.close()
                Clock.schedule_once(lambda dt: start_sequentie(self.totaal_pdf_paginas))
            except:
                pass

        def start_sequentie(totaal):
            self.pdf_overlay.width = Window.width * 0.9
            self.pdf_overlay.height = self.pdf_overlay.width * 1.41
            self.pdf_scroll_view.opacity = 1
            Animation(pos_hint={'center_x': 0.52, 'y': 0.02}, duration=0.5).start(self.pdf_controls)
            self.scroll_pagina(0, totaal)

        threading.Thread(target=verwerk_pdf, daemon=True).start()

    def check_handmatig_scrollen(self, instance, value):
        # Als er een animatie loopt, is de 'value' (scroll_y) aan het veranderen door de code.
        # Als we NIET aan het pauzeren zijn, maar de animatie wordt plotseling gestopt door een aanraking,
        # dan moeten we de pauze-status activeren.
        pass  # Deze functie gebruiken we vooral als back-up

    def handmatige_scroll_detectie(self, instance, touch):
        # Zodra de gebruiker begint te scrollen:
        if self.huidige_pdf_anim:
            self.huidige_pdf_anim.stop(self.pdf_scroll_view)
            self.huidige_pdf_anim = None

        # Zet op pauze en update de knop
        self.pdf_is_pauze = True
        self.btn_pauze.background_normal = os.path.join(ASSETS_DIR, 'verder_knop.png')
        self.log_status("HANDMATIG SCROLLEN: PAUZE")

    def scroll_pagina(self, index, totaal):
        if index >= totaal: self.sluit_pdf(); return
        self.huidige_pdf_index = index
        pad = os.path.join(TEMP_PDF_DIR, f"page_{index}.png")
        while not os.path.exists(pad): time.sleep(0.1)

        self.pdf_overlay.source = pad
        self.pdf_overlay.reload()

        # Alleen naar boven springen als we echt een NIEUWE pagina laden,
        # niet als we de huidige pagina hervatten.
        self.pdf_scroll_view.scroll_y = 1.0

        if index == 0: self.ui.opacity = 0

        # CRUCIALE CHECK: Start de animatie alleen als we niet gepauzeerd zijn
        if not self.pdf_is_pauze:
            # Stop eventuele oude animaties die nog "hangen"
            if self.huidige_pdf_anim:
                self.huidige_pdf_anim.stop(self.pdf_scroll_view)

            self.huidige_pdf_anim = Animation(scroll_y=0, duration=self.scroll_snelheid_standaard, t='linear')
            self.huidige_pdf_anim.bind(on_complete=self._pdf_anim_klaar)
            Clock.schedule_once(lambda dt: self._safe_start_anim(), 0.1)

    def _safe_start_anim(self):
        # Extra check vlak voor de start
        if not self.pdf_is_pauze and self.huidige_pdf_anim:
            self.huidige_pdf_anim.start(self.pdf_scroll_view)

    def _pdf_anim_klaar(self, *args):
        # Alleen wisselen als we echt onderaan zijn en NIET gepauzeerd
        if not self.pdf_is_pauze and self.pdf_scroll_view.scroll_y <= 0.02:
            self.wissel_pagina(1)

    def wissel_pagina(self, richting):
        nieuwe_index = self.huidige_pdf_index + richting
        if 0 <= nieuwe_index < self.totaal_pdf_paginas:
            if self.huidige_pdf_anim: self.huidige_pdf_anim.stop(self.pdf_scroll_view)
            self.scroll_pagina(nieuwe_index, self.totaal_pdf_paginas)

    def on_touch_down(self, touch):
        # Check of we in het PDF scherm zitten
        if self.pdf_scroll_view.opacity > 0.5:
            # Belangrijk: we checken of de touch BINNEN de scrollview valt
            if self.pdf_scroll_view.collide_point(*touch.pos):
                # STOP de animatie direct
                if self.huidige_pdf_anim:
                    self.huidige_pdf_anim.stop(self.pdf_scroll_view)
                    self.huidige_pdf_anim = None

                # Forceer pauze status
                self.pdf_is_pauze = True
                # Verander de knop direct (gebruik het volledige pad naar de asset)
                self.btn_pauze.background_normal = os.path.join(ASSETS_DIR, 'verder_knop.png')
                self.log_status("HANDMATIG SCROLLEN GESTART")

        # Dit zorgt ervoor dat de ScrollView de touch nog steeds krijgt om daadwerkelijk te kunnen scrollen
        return super(ChemieApp, self).on_touch_down(touch)

    def toggle_pauze(self, instance):
        # Als we nu aan het scrollen zijn (geen pauze), zet hem op pauze
        if not self.pdf_is_pauze:
            self.pdf_is_pauze = True
            if self.huidige_pdf_anim:
                self.huidige_pdf_anim.stop(self.pdf_scroll_view)
            instance.background_normal = os.path.join(ASSETS_DIR, 'verder_knop.png')
        else:
            # GA VERDER: start de animatie opnieuw vanaf de HUIDIGE scroll_y
            self.pdf_is_pauze = False
            instance.background_normal = os.path.join(ASSETS_DIR, 'pauze_knop.png')

            # Bereken resterende tijd op basis van hoe ver we zijn (scroll_y gaat van 1.0 naar 0.0)
            resterende_duur = self.pdf_scroll_view.scroll_y * self.scroll_snelheid_standaard

            if resterende_duur > 0:
                self.huidige_pdf_anim = Animation(scroll_y=0, duration=resterende_duur, t='linear')
                self.huidige_pdf_anim.bind(on_complete=self._pdf_anim_klaar)
                self.huidige_pdf_anim.start(self.pdf_scroll_view)

    def stop_noodprocedure(self, *args):
        """Stopt de timer, het alarm en herstelt de UI naar de standby-stand."""
        self.nood_actief = False
        self.systeem_bezet = False

        # Stop de timer-loop en het geluid
        if self.timer_event:
            self.timer_event.cancel()
            self.timer_event = None

        if self.alarm_sound:
            self.alarm_sound.stop()

        # Verberg de stopknop en de voortgangsbalk
        Animation(pos_hint={'center_x': 0.5, 'y': -0.2}, opacity=0, duration=0.5).start(self.btn_nood_stop)
        self.progress.opacity = 0

        # Reset de UI naar de standaard kleuren (Beige/Donkerblauw)
        self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER)
        self.log_status("SYSTEEM GEREED - NOODPROCEDURE GESTOPT")

        Animation(pos_hint={'center_x': 0.3, 'y': -0.2}, opacity=0, duration=0.5).start(self.btn_alarm_mute)
        Animation(pos_hint={'center_x': 0.7, 'y': -0.2}, opacity=0, duration=0.5).start(self.btn_nood_stop)

    def mute_alarm(self, instance):
        """Zet alleen het alarmgeluid uit, maar laat de timer doorlopen."""
        if self.alarm_sound:
            self.alarm_sound.stop()

        # Optioneel: verander de tekst van de knop of verberg hem
        instance.text = "ALARM UITGEZET"
        instance.disabled = True
        self.log_status("ALARM HANDMATIG UITGEZET DOOR COLLEGA")

    def sluit_pdf(self, *args):
        """Sluit alleen de PDF viewer en herstelt de UI."""
        self.systeem_bezet = False
        if self.huidige_pdf_anim:
            self.huidige_pdf_anim.stop(self.pdf_scroll_view)

        Animation(pos_hint={'center_x': 0.52, 'y': -0.2}, duration=0.5).start(self.pdf_controls)
        Animation(opacity=0, duration=0.5).start(self.pdf_scroll_view)
        Animation(opacity=1, duration=0.5).start(self.ui)

        self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER)

    # --- UI CORE ---
    def update_ui(self, tekst, hex_bg, hex_txt, pic_string=None):
        def change(dt):
            self.centraal_label.text = str(tekst).upper()
            Animation(rgba=get_color_from_hex(hex_bg), duration=0.6).start(self.bg_color)
            Animation(color=get_color_from_hex(hex_txt), duration=0.6).start(self.centraal_label)
            self.pic_layout.clear_widgets()
            if pic_string:
                for b in [x.strip() for x in pic_string.split(',') if x.strip()]:
                    p_path = os.path.join(PICTO_DIR, b)
                    if os.path.exists(p_path): self.pic_layout.add_widget(Image(source=p_path, allow_stretch=True))
                self.pic_layout.size_hint_y = 0.6
                self.centraal_label.size_hint_y = 0.4
            else:
                self.pic_layout.size_hint_y = 0.001
                self.centraal_label.size_hint_y = 1.0
        Clock.schedule_once(change)

    def log_status(self, bericht):
        # We printen het nog wel naar de PyCharm console voor jezelf
        print(f"STATUS: {bericht}")
        # Maar we werken het label op het scherm niet meer bij
        # self.status_label.text = bericht (deze regel zet je uit met een #)

    def _update_rect(self, instance, value):
        self.bg_rect.pos = instance.pos
        self.bg_rect.size = instance.size

    def start_intro_sequentie(self, dt):
        if self.intro_audio: self.intro_audio.play()
        anim = Animation(opacity=1, duration=INTRO_DUUR, t='out_quad')
        anim.bind(on_complete=self.activeer_spraak_systeem)
        anim.start(self.centraal_label)

    def activeer_spraak_systeem(self, *args):
        threading.Thread(target=self.initialiseer_audio_en_loop, daemon=True).start()

    def automatische_map_scanner(self):
        """Kijkt elke 5 seconden of er een nieuwe PDF in de map is gedropt."""
        while True:
            time.sleep(5)
            if self.nood_actief:
                continue

            nieuw_ontdekt = False
            if os.path.exists(MSDS_DIR):
                for bestand in os.listdir(MSDS_DIR):
                    if bestand.endswith('.pdf'):
                        s_id = "".join(bestand.lower().replace('.pdf', '').split())
                        if s_id not in self.lab_database:
                            print(f"[LIVE UPDATE]: Nieuw bestand gedetecteerd: {bestand}")
                            pdf_data = self.analyseer_msds_pdf(os.path.join(MSDS_DIR, bestand))
                            if pdf_data:
                                self.lab_database[s_id] = pdf_data
                                nieuw_ontdekt = True
                                print(f"[LIVE UPDATE]: '{pdf_data['naam']}' succesvol toegevoegd aan het geheugen!")

            if nieuw_ontdekt and not self.systeem_bezet:
                # Korte melding op het scherm dat de database is bijgewerkt
                self.log_status("DATABASE AUTOMATISCH BIJGEWERKT")

    def analyseer_msds_pdf(self, pdf_pad):
        """Opent de PDF, filtert sectie 2, 4 en 8, en koppelt automatisch de juiste pictogram-bestanden."""
        try:
            doc = fitz.open(pdf_pad)
            volledige_tekst = ""
            for pagina in doc:
                volledige_tekst += pagina.get_text()
            doc.close()

            stofnaam = Path(pdf_pad).stem.capitalize()
            tekst_low = volledige_tekst.lower()

            # --- 1. AUTOMATISCHE GEVAREN PICTOGRAMMEN (Alleen zoeken in Rubriek 2!) ---
            # --- 1. AUTOMATISCHE GEVAREN PICTOGRAMMEN (Scannen op officiële GHS-codes) ---
            gevonden_gevaren_pics = []

            # We isoleren nog steeds eerst Rubriek 2 voor de absolute nauwkeurigheid
            r2_match = re.search(r'(rubriek|sectie|section)\s*2', tekst_low)
            r3_match = re.search(r'(rubriek|sectie|section)\s*3', tekst_low)

            rubriek2_blok = ""
            if r2_match and r3_match:
                start_r2 = r2_match.start()
                eind_r2 = r3_match.start()
                if start_r2 < eind_r2:
                    rubriek2_blok = tekst_low[start_r2:eind_r2]

            # Als Rubriek 2 is gevonden, zoeken we daarin. Zo niet, dan scannen we de hele tekst.
            # Omdat GHS-codes zo specifiek zijn, kan dit nu veilig allebei!
            zoek_gebied_gevaren = rubriek2_blok if rubriek2_blok else tekst_low

            # --- GHS CODE CHECKER ---
            if "ghs01" in zoek_gebied_gevaren:
                gevonden_gevaren_pics.append("explosief.png")

            if "ghs02" in zoek_gebied_gevaren:
                gevonden_gevaren_pics.append("Brandbaar.png")

            if "ghs03" in zoek_gebied_gevaren:
                gevonden_gevaren_pics.append("oxiderend.png")

            if "ghs04" in zoek_gebied_gevaren:
                gevonden_gevaren_pics.append("gassen.png")  # (Gas onder druk)

            if "ghs05" in zoek_gebied_gevaren:
                gevonden_gevaren_pics.append("Corrosief.png")

            if "ghs06" in zoek_gebied_gevaren:
                gevonden_gevaren_pics.append("giftig.png")

            if "ghs07" in zoek_gebied_gevaren:
                gevonden_gevaren_pics.append("!.png")

            if "ghs08" in zoek_gebied_gevaren:
                gevonden_gevaren_pics.append("ongezond.png")

            if "ghs09" in zoek_gebied_gevaren:
                gevonden_gevaren_pics.append("milieu.png")

            pictogrammen_string = ",".join(gevonden_gevaren_pics)

            # --- 2. AUTOMATISCHE PBM PICTOGRAMMEN (Sectie 8 met Slimme Volledige Tekst Fallback) ---
            gevonden_pbm_pics = []
            pbm_tekst = "Draag de standaard beschermingsmiddelen."

            # 1. We proberen Rubriek 8 te isoleren via verschillende lay-out stijlen
            r8_match = re.search(r'(rubriek|sectie|section|hoofdstuk)\s*8', tekst_low)
            if not r8_match:
                r8_match = re.search(r'(^|\n)\s*8[\.\s]',
                                     tekst_low)  # Zoekt naar "8. " of "8 " aan het begin van een regel

            r9_match = re.search(r'(rubriek|sectie|section|hoofdstuk)\s*9', tekst_low)
            if not r9_match:
                r9_match = re.search(r'(^|\n)\s*9[\.\s]', tekst_low)

            pbm_blok = ""
            if r8_match and r9_match:
                start_r8 = r8_match.start()
                eind_r8 = r9_match.start()
                if start_r8 < eind_r8:
                    pbm_blok = tekst_low[start_r8:eind_r8]

            # 2. DE REDDINGSBOEI: Als het blok niet is gevonden, scannen we veilig de GEHELE tekst!
            zoek_gebied_pbm = pbm_blok if pbm_blok else tekst_low
            if not pbm_blok:
                print("[DEBUG]: Rubriek 8 blok niet scherp gevonden, fallback naar volledige tekst-scan actief.")
            else:
                print("[DEBUG]: Rubriek 8 succesvol geïsoleerd.")

            gevonden_pbm = []

            # 1. UITGEBREID ZOEKEN NAAR BRIL / OOGBESCHERMING
            termen_bril = ["bril", "oog", "gelaat", "en 166", "en166", "face shield", "spectacles"]
            if any(t in zoek_gebied_pbm for t in termen_bril):
                gevonden_pbm.append("een veiligheidsbril")
                gevonden_pbm_pics.append("bril.png")

            # 2. UITGEBREID ZOEKEN NAAR HANDSCHOENEN
            termen_handschoen = ["handschoen", "nitril", "rubber", "en 374", "en374", "gloves", "manchet"]
            if any(t in zoek_gebied_pbm for t in termen_handschoen):
                gevonden_pbm.append("chemiebestendige handschoenen")
                gevonden_pbm_pics.append("handschoenen.png")

            # 3. UITGEBREID ZOEKEN NAAR MASKER / ADEMHALING
            termen_masker = ["masker", "ademhaling", "filter", "f动", "ffp", "en 143", "en 149", "respirator"]
            if any(t in zoek_gebied_pbm for t in termen_masker):
                gevonden_pbm.append("ademhalingsbescherming")
                gevonden_pbm_pics.append("masker.png")

            # 4. UITGEBREID ZOEKEN NAAR SCHORT / ZWARE BESCHERMING
            termen_schort = ["schort", "overall", "pak", "en 13034", "en13034", "apron", "chemical suit"]
            if any(t in zoek_gebied_pbm for t in termen_schort):
                gevonden_pbm.append("beschermende kleding")
                gevonden_pbm_pics.append("schort.png")

            # 5. UITGEBREID ZOEKEN NAAR VEILIGHEIDSSCHOENEN
            termen_schoenen = ["schoen", "laars", "laarzen", "schoeisel", "en 20345", "en20345", "en 13832", "boots",
                               "footwear"]
            if any(t in zoek_gebied_pbm for t in termen_schoenen):
                gevonden_pbm.append("veiligheidsschoenen")
                gevonden_pbm_pics.append("schoenen.png")

            # 6. UITGEBREID ZOEKEN NAAR GEHOORBESCHERMING
            termen_gehoor = ["gehoor", "oor", "oordoppen", "oorkappen", "en 352", "en352", "hearing", "earmuffs"]
            if any(t in zoek_gebied_pbm for t in termen_gehoor):
                gevonden_pbm.append("gehoorbescherming")
                gevonden_pbm_pics.append("gehoor.png")

            # 7. UITGEBREID ZOEKEN NAAR STANDAARD WERKKLEDING
            termen_werkkleding = ["werkkleding", "kleding", "werkbroek", "jassen", "clothing", "workwear"]
            if any(t in zoek_gebied_pbm for t in termen_werkkleding) and "schort.png" not in gevonden_pbm_pics:
                gevonden_pbm.append("geschikte werkkleding")
                gevonden_pbm_pics.append("werkkleding.png")

            # 8. UITGEBREID ZOEKEN NAAR VEILIGHEIDSHELMEN
            termen_helm = ["helm", "hoofdbescherming", "veiligheidshelm", "en 397", "en397", "en 14052", "helmet",
                           "head protection"]
            if any(t in zoek_gebied_pbm for t in termen_helm):
                gevonden_pbm.append("een veiligheidshelm")
                gevonden_pbm_pics.append("helm.png")

            if gevonden_pbm:
                pbm_tekst = "Draag in ieder geval: " + ", ".join(gevonden_pbm) + "."

            # Deze regel bouwt de string op voor de UI
            pbm_pics_string = ",".join(gevonden_pbm_pics)

            # --- 3. SECTIE 4: OOG-SPOEL INSTRUCTIE ---
            oog_tekst = "Bij contact met de ogen, direct spoelen met overvloedig water en een arts raadplegen."
            if "rubriek 4" in tekst_low or "sectie 4" in tekst_low:
                start = tekst_low.find("rubriek 4") if "rubriek 4" in tekst_low else tekst_low.find("sectie 4")
                eind = tekst_low.find("rubriek 5") if "rubriek 5" in tekst_low else tekst_low.find("sectie 5")
                if start != -1 and eind != -1:
                    oog_blok = tekst_low[start:eind]
                    for regel in oog_blok.split('\n'):
                        if "oog" in regel or "ogen" in regel:
                            if len(regel.strip()) > 15:
                                oog_tekst = regel.strip().capitalize()
                                break

            # --- 4. SECTIE 2: GEVAREN FILTER ---
            gevaren_tekst = "Zie het veiligheidsblad voor de specifieke gevaren."
            if "rubriek 2" in tekst_low or "sectie 2" in tekst_low:
                start = tekst_low.find("rubriek 2") if "rubriek 2" in tekst_low else tekst_low.find("sectie 2")
                eind = tekst_low.find("rubriek 3") if "rubriek 3" in tekst_low else tekst_low.find("sectie 3")
                if start != -1 and eind != -1:
                    gevaren_blok = tekst_low[start:eind]
                    h_zinnen = []
                    for regel in gevaren_blok.split('\n'):
                        if "h2" in regel or "h3" in regel or "h4" in regel or "veroorzaakt" in regel or "gevaar" in regel:
                            if len(regel.strip()) > 15 and regel.strip() not in h_zinnen:
                                h_zinnen.append(regel.strip())
                    if h_zinnen:
                        gevaren_tekst = "Belangrijkste gevaren: " + " ".join(h_zinnen[:2])

            # Stuur het complete pakketje terug naar het geheugen
            return {
                "naam": stofnaam,
                "pbm_lab": pbm_tekst,
                "pbm_fabriek": pbm_tekst,
                "pbm_pic_lab": pbm_pics_string,  # Nu automatisch gevuld met PBM pics!
                "pbm_pic_fabriek": pbm_pics_string,  # Nu automatisch gevuld met PBM pics!
                "pictogram": pictogrammen_string,  # Nu automatisch gevuld met Gevaren pics!
                "n_ogen": oog_tekst,
                "msds": Path(pdf_pad).name,
                "gevaren": gevaren_tekst
            }
        except Exception as e:
            print(f"Fout bij uitlezen PDF {pdf_pad}: {e}")
            return None

    def laad_stoffen(self):
        """Laadt eerst de CSV en scant daarna de MSDS map voor automatische updates."""
        db = {}

        # 1. Bestaande CSV inlezen (als basis of back-up)
        if os.path.exists('stoffen.csv'):
            try:
                with open('stoffen.csv', mode='r', encoding='utf-8-sig') as f:
                    header = f.readline()
                    sep = ';' if ';' in header else ','
                    f.seek(0)
                    reader = csv.DictReader(f, delimiter=sep)
                    for row in reader:
                        clean_row = {k.strip().lower(): v for k, v in row.items() if k}
                        naam = clean_row.get('stof', next(iter(clean_row.values()))).strip()
                        s_id = "".join(naam.lower().split())
                        db[s_id] = {
                            "naam": naam,
                            "pbm_lab": clean_row.get('pbm_lab', ""),
                            "pbm_fabriek": clean_row.get('pbm_fabriek', ""),
                            "pbm_pic_lab": clean_row.get('pbm_pic_lab', ""),
                            "pbm_pic_fabriek": clean_row.get('pbm_pic_fabriek', ""),
                            "pictogram": clean_row.get('pictogram', ""),
                            "n_ogen": next((v for k, v in clean_row.items() if 'ogen' in k), ""),
                            "msds": clean_row.get('msds', ""),
                            "gevaren": clean_row.get('gevaren', "Er zijn geen specifieke gevaren bekend.")
                        }
            except Exception as e:
                print(f"Fout bij laden CSV: {e}")

        # 2. Scoor de MSDS map voor PDF's en vul aan/overschrijf
        if os.path.exists(MSDS_DIR):
            for bestand in os.listdir(MSDS_DIR):
                if bestand.endswith('.pdf'):
                    s_id = "".join(bestand.lower().replace('.pdf', '').split())
                    # Als de stof nog NIET in de database staat, lees hem dan live uit
                    if s_id not in db:
                        print(f"[MAP-SCANNER]: Nieuwe stof ontdekt via PDF: {bestand}")
                        pdf_data = self.analyseer_msds_pdf(os.path.join(MSDS_DIR, bestand))
                        if pdf_data:
                            db[s_id] = pdf_data
        return db

    def vind_beste_stof(self, opdracht):
        if not opdracht: return None

        # 1. Woorden die we negeren omdat het geen stoffen zijn
        stopwoorden = ["wat", "zijn", "de", "het", "van", "gevaar", "gevaren",
                       "risico", "pbm", "informatie", "msds", "blad", "laat", "zien"]

        # 2. Maak de zin schoon: verwijder leestekens en zet in kleine letters
        woorden = opdracht.lower().replace("?", "").replace("!", "").split()

        # 3. Filter de stopwoorden eruit zodat alleen de mogelijke stofnaam overblijft
        gefilterde_woorden = [w for w in woorden if w not in stopwoorden]

        print(f"[DEBUG] Woorden na filteren: {gefilterde_woorden}")

        beste_match = None
        hoogste_score = 0

        # 4. Zoek per woord (of combinatie) naar de beste match in de database
        for woord in gefilterde_woorden:
            matches = difflib.get_close_matches(woord, list(self.lab_database.keys()), n=1, cutoff=0.6)
            if matches:
                # We pakken de match die het meest lijkt op wat er gezegd is
                beste_match = matches[0]
                break

        if beste_match:
            print(f"[MATCH GEVONDEN]: Gekoppeld aan stof ID: '{beste_match}'")
            return beste_match
        else:
            print(f"[GEEN MATCH]: Kon geen stof herkennen in de zin: '{opdracht}'")
            return None

    def hoofd_loop(self):
        if platform != 'android':
            self.recognizer = sr.Recognizer()
            self.recognizer.energy_threshold = 300
            self.recognizer.dynamic_energy_threshold = False
            self.recognizer.pause_threshold = 0.5

        self.log_status("SYSTEEM GEREED - LUISTEREND...")

        while True:
            if self.nood_actief:
                time.sleep(1)
                continue

            try:
                input_t = ""

                if platform == 'android':
                    # --- ANDROID PLAATSVERVANGER ---
                    # Hier moeten we de Kivy-Android spraakherkenning inbouwen.
                    # Voor nu zetten we hem op slaapstand zodat de app op tablet niet crasht.
                    time.sleep(2)
                else:
                    # --- JOUW ORIGINELE WINDOWS CODE ---
                    with sr.Microphone() as source:
                        audio = self.recognizer.listen(source, timeout=None, phrase_time_limit=3)
                    input_t = self.recognizer.recognize_google(audio, language="nl-NL").lower()

                # Als er niets gehoord is (of als we op Android testen), begin de loop opnieuw
                if not input_t:
                    continue

                print(f"[GEHOORD]: {input_t}")

                # --- 1. TRIGGER CHECK ---
                nood_woorden = ["oog", "ogen", "nood", "help", "spoelen"]

                if any(w in input_t for w in nood_woorden) and "chemie" not in input_t:
                    s_id = self.vind_beste_stof(input_t)
                    if s_id:
                        print(f"!!! DIRECTE NOOD-ACTIE !!!")
                        info = self.lab_database[s_id]
                        Clock.schedule_once(lambda dt: self.start_nood_timer(info))
                        continue

                # --- 2. NORMALE ACTIVATIE ---
                if "chemie" in input_t:
                    if self.ping_sound: self.ping_sound.play()
                    print("Assistent geactiveerd!")

                    Clock.schedule_once(lambda dt: self.update_ui("LUISTEREN", "#F0D876", "#273f53"))
                    self.assistent_spreekt("Wat kan ik voor u doen?")
                    if self.ping_sound: self.ping_sound.play()

                    try:
                        # Open de microfoon opnieuw specifiek voor de vervolgvraag
                        with sr.Microphone() as source:
                            audio_v = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)

                        vraag = self.recognizer.recognize_google(audio_v, language="nl-NL").lower()
                        print(f"[VRAAG]: {vraag}")

                        s_id = self.vind_beste_stof(vraag)
                        if s_id:
                            info = self.lab_database[s_id]
                            if any(x in vraag for x in ["gevaar", "risico", "gevaarlijk"]):
                                self.lees_gevaren_voor(info)
                            elif any(x in vraag for x in ["pdf", "msds", "blad"]):
                                self.open_msds(info)
                            else:
                                self.systeem_bezet = True
                                threading.Thread(target=self.vraag_locatie_en_antwoord, args=(info,),
                                                 daemon=True).start()
                        else:
                            self.assistent_spreekt("Stof niet herkend.")
                    except sr.UnknownValueError:
                        print("Geen vraag begrepen na activatie.")
                    except sr.WaitTimeoutError:
                        print("Wachttijd voor vraag verlopen.")

            except sr.UnknownValueError:
                pass
            except Exception as e:
                # Mocht er TOCH een audio-fout optreden, dan crasht de loop nu niet meer,
                # maar wacht hij 1 seconde en probeert het opnieuw.
                print(f"Loop error opgevangen: {e}")
                time.sleep(1)

            # --- RESET UI ---
            if not self.nood_actief and not self.systeem_bezet:
                if self.centraal_label.text != "CHEMI":
                    Clock.schedule_once(lambda dt: self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER))

    def initialiseer_audio_en_loop(self):
        self.schoonmaak_bij_opstart()
        self.lab_database = self.laad_stoffen()
        threading.Thread(target=self.automatische_map_scanner, daemon=True).start()
        self.log_status("SYSTEEM GEREED - LUISTEREND...")
        self.hoofd_loop()

    def schoonmaak_bij_opstart(self):
        """Verwijdert oude spraakbestanden en tijdelijke PDF plaatjes."""
        # 1. Spraakbestanden in de hoofdmap
        for vijl in os.listdir('.'):
            if vijl.startswith("spraak_") and vijl.endswith(".mp3"):
                try:
                    os.remove(vijl)
                except:
                    pass

        # 2. Oude PDF plaatjes in de temp map
        if os.path.exists(TEMP_PDF_DIR):
            for afbeelding in os.listdir(TEMP_PDF_DIR):
                try:
                    os.remove(os.path.join(TEMP_PDF_DIR, afbeelding))
                except:
                    pass
        self.log_status("TIJDELIJKE BESTANDEN OPGESCHOOND")

    def lees_gevaren_voor(self, info):
        self.systeem_bezet = True
        gevaren_tekst = info.get('gevaren', "Er zijn geen specifieke gevaren bekend voor deze stof.")

        Clock.schedule_once(
            lambda dt: self.update_ui(f"GEVAREN: {info['naam']}", "#FF4500", "#FFFFFF", info['pictogram']))

        # VEILIGE CHECK OP BESTAAN VAN TAAL-VARIABELE:
        taal = getattr(self, 'huidige_taal', 'nl')

        if taal == "en":
            intro = f"The hazards for {info['naam']} are: "
            tekst = info.get('gevaren_en', gevaren_tekst)
        else:
            intro = f"De gevaren van {info['naam']} zijn: "
            tekst = gevaren_tekst

        self.assistent_spreekt(intro + tekst)

        # Even wachten zodat mensen het kunnen lezen op het scherm
        time.sleep(4.0)
        self.systeem_bezet = False
        Clock.schedule_once(lambda dt: self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER))

    def open_msds(self, info):
        """Bouwt het pad naar de PDF en start de weergave."""
        pdf_naam = info.get('msds', '')
        if pdf_naam:
            pdf_pad = os.path.join(MSDS_DIR, pdf_naam)
            if os.path.exists(pdf_pad):
                print(f"[MSDS]: Openen van {pdf_pad}")
                Clock.schedule_once(lambda dt: self.toon_pdf_in_app(pdf_pad))
            else:
                self.assistent_spreekt("Het veiligheidsblad is niet gevonden in de map.")
        else:
            self.assistent_spreekt("Er is geen veiligheidsblad gekoppeld aan deze stof.")

if __name__ == '__main__':
    ChemieApp().run()