import os
import csv
import time
import re
import asyncio
import threading
import difflib

from pathlib import Path
from pypdf import PdfReader

from kivy.config import Config
Config.set("graphics", "multisamples", "0")
Config.set("graphics", "always_on_top", "0")
Config.set("graphics", "maxfps", "60")
Config.set("graphics", "fullscreen", "auto")
Config.set("kivy", "log_level", "error")

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.image import Image
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivy.clock import Clock
from kivy.utils import get_color_from_hex, platform
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.core.audio import SoundLoader
from kivy.graphics import Color, Rectangle
from kivy.animation import Animation
from kivy.properties import NumericProperty

if platform != "android":
    try:
        import edge_tts
    except ImportError:
        edge_tts = None
    try:
        import speech_recognition as sr
    except ImportError:
        sr = None
else:
    edge_tts = None
    sr = None

if platform == "android":
    try:
        from android.permissions import request_permissions, Permission
        from android_listener import AndroidContinuousListener
    except ImportError as fout:
        print(f"Androidmodules konden niet worden geladen: {fout}")
        request_permissions = None
        Permission = None
        AndroidContinuousListener = None
else:
    request_permissions = None
    Permission = None
    AndroidContinuousListener = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
PICTO_DIR = os.path.join(BASE_DIR, "pictogrammen")
MSDS_DIR = os.path.join(BASE_DIR, "msds")
STOFFEN_CSV = os.path.join(BASE_DIR, "stoffen.csv")

BG_STANDBY = "#F5EFDB"
KLEUR_TEKST_DONKER = "#273F53"
KLEUR_LUISTEREN = "#2ECC71"
KLEUR_VRAAG = "#F1C40F"
KLEUR_NOOD = "#E74C3C"
KLEUR_KEUZE = "#3498DB"
KLEUR_MUTE = "#FFFFFF"
KLEUR_TEKST_WIT = "#E74C3C"
INTRO_DUUR = 2.5
Window.clearcolor = get_color_from_hex(BG_STANDBY)

FONT_PAD = os.path.join(ASSETS_DIR, "Monas-BLBW8.ttf")
try:
    if os.path.exists(FONT_PAD):
        LabelBase.register(name="MijnFont", fn_regular=FONT_PAD)
        GEBRUIK_FONT = "MijnFont"
    else:
        GEBRUIK_FONT = "Roboto"
except Exception as fout:
    print(f"Lettertype kon niet worden geladen: {fout}")
    GEBRUIK_FONT = "Roboto"


class ProgressWidget(Widget):
    value = NumericProperty(900)
    max = NumericProperty(900)


class ChemieApp(App):
    def build(self):
        Window.fullscreen = "auto"
        self.nood_actief = False
        self.systeem_bezet = False
        self.pdf_is_pauze = False
        self.gekozen_locatie = None
        self.keuze_event = threading.Event()
        self.huidige_pdf_anim = None
        self.huidige_pdf_index = 0
        self.totaal_pdf_paginas = 0
        self.pdf_paginas_tekst = []
        self.scroll_snelheid_standaard = 40
        self.lab_database = {}
        self.timer_seconds = 900
        self.timer_event = None
        self.recognizer = None

        self.android_listener = None
        self.wacht_op_opdracht = False
        self.wacht_op_locatie = False
        self.huidige_spraak_info = None
        self.laatste_noodactie = 0
        self.android_spraak_actief = False

        self.DATA_DIR = self.user_data_dir
        self.TEMP_PDF_DIR = os.path.join(self.DATA_DIR, "temp_pdf")
        self.NOODLOG_PAD = os.path.join(self.DATA_DIR, "noodlog.csv")
        self.maak_schrijfbare_mappen()

        self.alarm_sound = self.laad_geluid("alarm.wav")
        self.ping_sound = self.laad_geluid("ping.wav")
        self.intro_audio = self.laad_geluid("intro_audio.mp3")

        self.root_layout = FloatLayout()
        with self.root_layout.canvas.before:
            self.bg_color = Color(rgba=get_color_from_hex(BG_STANDBY))
            self.bg_rect = Rectangle(size=Window.size, pos=(0, 0))
        self.root_layout.bind(size=self._update_rect, pos=self._update_rect)

        self.ui = BoxLayout(orientation="vertical", padding=50, spacing=20, size_hint=(1, 1))
        self.pic_layout = BoxLayout(orientation="horizontal", size_hint=(1, 0.001), spacing=20)
        self.centraal_label = Label(
            text="CHEMI", font_name=GEBRUIK_FONT, font_size="100sp", opacity=0,
            bold=True, halign="center", valign="middle",
            color=get_color_from_hex(KLEUR_TEKST_DONKER)
        )
        self.centraal_label.bind(size=self._update_label_text_size)
        self.status_log = Label(
            text="OPSTARTEN...", font_size="14sp", size_hint=(1, 0.1),
            color=get_color_from_hex("#7F8C8D"), halign="center", valign="middle"
        )
        self.status_log.bind(size=self._update_label_text_size)

        self.progress = ProgressWidget(
            size_hint=(0.6, 0.01), pos_hint={"center_x": 0.5, "y": 0.15}, opacity=0
        )
        with self.progress.canvas:
            self.bg_bar_color = Color(rgba=get_color_from_hex("#BDC3C7"))
            self.bar_bg_rect = Rectangle(pos=self.progress.pos, size=self.progress.size)
            self.fill_bar_color = Color(rgba=get_color_from_hex("#FFFFFF"))
            self.bar_fill_rect = Rectangle(pos=self.progress.pos, size=self.progress.size)
        self.progress.bind(
            pos=self.update_progress_rects, size=self.update_progress_rects,
            value=self.update_progress_rects, max=self.update_progress_rects
        )

        self.ui.add_widget(self.pic_layout)
        self.ui.add_widget(self.centraal_label)
        self.ui.add_widget(self.status_log)
        self.root_layout.add_widget(self.ui)
        self.root_layout.add_widget(self.progress)

        self.btn_layout_locatie = BoxLayout(
            orientation="horizontal", size_hint=(None, None), size=(500, 75),
            pos_hint={"center_x": 0.5, "y": -0.3}, spacing=40, opacity=0
        )
        btn_style = {"background_normal": "", "font_size": "22sp", "bold": True}
        self.btn_lab = Button(text="LABORATORIUM", background_color=get_color_from_hex(KLEUR_TEKST_DONKER), **btn_style)
        self.btn_fabriek = Button(text="FABRIEK", background_color=get_color_from_hex(KLEUR_TEKST_DONKER), **btn_style)
        self.btn_lab.bind(on_release=lambda knop: self.set_locatie("lab"))
        self.btn_fabriek.bind(on_release=lambda knop: self.set_locatie("fabriek"))
        self.btn_layout_locatie.add_widget(self.btn_lab)
        self.btn_layout_locatie.add_widget(self.btn_fabriek)
        self.root_layout.add_widget(self.btn_layout_locatie)

        self.btn_nood_stop = Button(
            text="STOP NOODPROCEDURE", size_hint=(None, None), size=(400, 100),
            pos_hint={"center_x": 0.7, "y": -0.2}, background_normal="",
            background_color=(1, 1, 1, 1), color=get_color_from_hex(KLEUR_NOOD),
            bold=True, font_size="24sp", opacity=0
        )
        self.btn_nood_stop.bind(on_release=self.stop_noodprocedure)
        self.root_layout.add_widget(self.btn_nood_stop)

        self.btn_alarm_mute = Button(
            text="ALARM\nDEMPEN", size_hint=(None, None), size=(220, 100),
            pos_hint={"center_x": 0.3, "y": -0.2}, background_normal="",
            background_color=get_color_from_hex(KLEUR_MUTE),
            color=get_color_from_hex(KLEUR_TEKST_WIT), bold=True,
            halign="center", font_size="20sp", opacity=0
        )
        self.btn_alarm_mute.bind(on_release=self.mute_alarm)
        self.root_layout.add_widget(self.btn_alarm_mute)

        self.pdf_scroll_view = ScrollView(
            size_hint=(0.9, 0.80), pos_hint={"center_x": 0.5, "center_y": 0.58},
            do_scroll_x=False, do_scroll_y=True, opacity=0
        )
        self.pdf_scroll_view.bind(on_scroll_start=self.handmatige_scroll_detectie)
        self.pdf_controls = BoxLayout(
            orientation="horizontal", size_hint=(None, None), size=(550, 110),
            pos_hint={"center_x": 0.52, "y": -0.2}, padding=10, spacing=20
        )
        self.btn_prev = Button(background_normal=self.asset_pad("vorige_knop.png"), size_hint=(None, None), size=(100, 100))
        self.btn_pauze = Button(background_normal=self.asset_pad("pauze_knop.png"), size_hint=(None, None), size=(100, 100))
        self.btn_next = Button(background_normal=self.asset_pad("volgende_knop.png"), size_hint=(None, None), size=(100, 100))
        self.btn_stop = Button(background_normal=self.asset_pad("stop_knop.png"), size_hint=(None, None), size=(100, 100))
        self.btn_prev.bind(on_release=lambda knop: self.wissel_pagina(-1))
        self.btn_pauze.bind(on_release=self.toggle_pauze)
        self.btn_next.bind(on_release=lambda knop: self.wissel_pagina(1))
        self.btn_stop.bind(on_release=self.sluit_pdf)
        for widget in [self.btn_prev, self.btn_pauze, self.btn_next, self.btn_stop]:
            self.pdf_controls.add_widget(widget)
        self.root_layout.add_widget(self.pdf_scroll_view)
        self.root_layout.add_widget(self.pdf_controls)

        Clock.schedule_once(self.start_intro_sequentie, 0.5)
        return self.root_layout

    def on_start(self):
        if platform == "android":
            self.vraag_android_permissies()
            Clock.schedule_once(self.start_android_listener,10.0)

    def on_stop(self):
        if platform == "android" and self.android_listener is not None:
            try:
                self.android_listener.stop()
            except Exception as fout:
                print(f"Luisterservice kon niet netjes stoppen: {fout}")

    def vraag_android_permissies(self):
        if request_permissions is None or Permission is None:
            print("Android-permissiemodule is niet beschikbaar.")
            return
        try:
            permissies = [Permission.RECORD_AUDIO]
            if hasattr(Permission, "READ_EXTERNAL_STORAGE"):
                permissies.append(Permission.READ_EXTERNAL_STORAGE)
            if hasattr(Permission, "WRITE_EXTERNAL_STORAGE"):
                permissies.append(Permission.WRITE_EXTERNAL_STORAGE)
            request_permissions(permissies)
        except Exception as fout:
            print(f"Android-permissies konden niet worden aangevraagd: {fout}")

    def start_android_listener(self, dt=None):
        if platform != "android":
            return
        if AndroidContinuousListener is None:
            self.android_luisterfout("ANDROID LUISTERMODULE ONTBREEKT")
            return
        try:
            if self.android_listener is None:
                self.android_listener = AndroidContinuousListener(
                    on_text=self.verwerk_android_spraak,
                    on_status=self.android_luisterstatus,
                    on_error=self.android_luisterfout,
                    language="nl-NL"
                )
            self.android_listener.start()
        except Exception as fout:
            self.android_luisterfout(f"LUISTERSERVICE KON NIET STARTEN: {fout}")

    def android_luisterstatus(self, status):
        self.android_spraak_actief = status in (
            "MICROFOON ACTIEF - ZEG CHEMI", "MICROFOON START...",
            "SPRAAK GEHOORD", "SPRAAK VERWERKEN..."
        )
        self.log_status(status)
        if status == "MICROFOON ACTIEF - ZEG CHEMI":
            self.status_log.color = get_color_from_hex("#27AE60")
        elif status in ("MICROFOON START...", "SPRAAK GEHOORD", "SPRAAK VERWERKEN...", "MICROFOON HERSTART..."):
            self.status_log.color = get_color_from_hex("#F1C40F")
        else:
            self.status_log.color = get_color_from_hex("#E74C3C")

    def android_luisterfout(self, fout):
        self.android_spraak_actief = False
        self.log_status(f"WAARSCHUWING: {fout}")
        if hasattr(self, "status_log"):
            self.status_log.color = get_color_from_hex("#E74C3C")

    def verwerk_android_spraak(self, gesproken_tekst):
        try:
            tekst = str(gesproken_tekst).lower().strip()
    
            print(
                f"[ANDROID GEHOORD\]: {tekst}"
            )
    
            if not tekst:
                return
    
            # Tijdens een actieve noodprocedure alleen
            # stopopdrachten verwerken.
            if self.nood_actief:
                stopopdrachten = [
                    "stop noodprocedure",
                    "stop alarm",
                    "alarm stoppen"
                ]
    
                if any(
                    opdracht in tekst
                    for opdracht in stopopdrachten
                ):
                    self.stop_noodprocedure()
    
                return
    
            # Gesproken locatiekeuze verwerken.
            if self.wacht_op_locatie:
                if (
                    "laboratorium" in tekst
                    or tekst == "lab"
                    or "het lab" in tekst
                ):
                    self.wacht_op_locatie = False
                    self.set_locatie("lab")
                    return
    
                if (
                    "fabriek" in tekst
                    or "productie" in tekst
                    or "de hal" in tekst
                ):
                    self.wacht_op_locatie = False
                    self.set_locatie("fabriek")
                    return
    
            # Directe noodmeldingen.
            noodzinnen = [
                "noodgeval",
                "help",
                "in mijn ogen",
                "in de ogen",
                "vloeistof in ogen",
                "vloeistof in mijn ogen",
                "chemische stof in ogen",
                "chemische stof in mijn ogen",
                "ogen spoelen",
                "oog spoelen",
                "spoel mijn ogen",
                "brand in mijn ogen"
            ]
    
            if any(
                noodzin in tekst
                for noodzin in noodzinnen
            ):
                huidige_tijd = time.time()
    
                # Voorkom dat hetzelfde spraakresultaat
                # meerdere noodprocedures start.
                if (
                    huidige_tijd
                    - self.laatste_noodactie
                    < 5
                ):
                    return
    
                self.laatste_noodactie = huidige_tijd
                self.wacht_op_opdracht = False
    
                print(
                    "[ANDROID ACTIE\]: "
                    "DIRECTE NOODMELDING HERKEND"
                )
    
                self.verwerk_android_noodgeval(
                    tekst
                )
                return
    
            # Als eerder alleen "Chemi" is gezegd,
            # behandelen we deze tekst als vervolgopdracht.
            if self.wacht_op_opdracht:
                self.wacht_op_opdracht = False
    
                print(
                    "[ANDROID ACTIE\]: "
                    f"VERVOLGOPDRACHT: {tekst}"
                )
    
                self.verwerk_android_opdracht(
                    tekst
                )
                return
    
            # Normale wake-word detectie.
            if (
                "chemi" in tekst
                or "chemie" in tekst
            ):
                opdracht = tekst
    
                opdracht = opdracht.replace(
                    "chemie",
                    "",
                    1
                )
    
                opdracht = opdracht.replace(
                    "chemi",
                    "",
                    1
                )
    
                opdracht = opdracht.strip(
                    " ,.!?"
                )
    
                # Bijvoorbeeld:
                # "Chemie open het MSDS van methanol"
                if opdracht:
                    print(
                        "[ANDROID ACTIE\]: "
                        f"DIRECTE OPDRACHT: {opdracht}"
                    )
    
                    self.verwerk_android_opdracht(
                        opdracht
                    )
                    return
    
                # Alleen het wake-word is gehoord.
                self.wacht_op_opdracht = True
    
                print(
                    "[ANDROID ACTIE\]: "
                    "WAKE-WORD CHEMI HERKEND"
                )
    
                self.update_ui(
                    "WAT KAN IK VOOR U DOEN?",
                    KLEUR_VRAAG,
                    KLEUR_TEKST_DONKER
                )
    
                self.speel_geluid(
                    self.ping_sound
                )
    
                Clock.schedule_once(
                    self.reset_wachten_op_opdracht,
                    10
                )
    
                return
    
            print(
                "[ANDROID ACTIE\]: "
                "TEKST BEVAT GEEN WAKE-WORD OF NOODMELDING"
            )
    
        except Exception as fout:
            print(
                "[ANDROID FOUT VERWERK_SPRAAK\]: "
                f"{type(fout).__name__}: {fout}"
            )
    
            self.log_status(
                "FOUT BIJ VERWERKEN VAN SPRAAK"
            )
        
    def reset_wachten_op_opdracht(self, dt=None):
        if self.wacht_op_opdracht:
            self.wacht_op_opdracht = False
            if not self.nood_actief:
                self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER)

    def verwerk_android_noodgeval(self, tekst):
        self.log_status(f"NOODMELDING GEHOORD: {tekst}")
        stof_id = self.vind_beste_stof(tekst)
        if stof_id and stof_id in self.lab_database:
            info = self.lab_database[stof_id]
        else:
            info = {
                "naam": "ONBEKENDE STOF", "pictogram": "",
                "n_ogen": "Begin direct met het spoelen van de ogen. Volg de bestaande noodprocedure en waarschuw direct een collega.",
                "pbm_lab": "", "pbm_fabriek": "", "pbm_pic_lab": "",
                "pbm_pic_fabriek": "", "msds": "", "gevaren": ""
            }
        self.log_noodgeval(info.get("naam", "ONBEKENDE STOF"))
        self.start_nood_timer(info, minuten=15)

    def verwerk_android_opdracht(self, tekst):
        self.log_status(f"OPDRACHT GEHOORD: {tekst}")
        stof_id = self.vind_beste_stof(tekst)
        if not stof_id:
            self.update_ui("STOF NIET HERKEND", KLEUR_VRAAG, KLEUR_TEKST_DONKER)
            Clock.schedule_once(lambda dt: self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER), 3)
            return
        info = self.lab_database[stof_id]
        if any(w in tekst for w in ["oog", "ogen", "spoelen", "nood", "help"]):
            self.log_noodgeval(info.get("naam", "ONBEKENDE STOF"))
            self.start_nood_timer(info, minuten=15)
        elif any(w in tekst for w in ["gevaar", "gevaren", "risico", "gevaarlijk"]):
            threading.Thread(target=self.lees_gevaren_voor, args=(info,), daemon=True).start()
        elif any(w in tekst for w in ["pdf", "msds", "veiligheidsblad", "veiligheidsinformatieblad", "blad"]):
            self.open_msds(info)
        else:
            threading.Thread(target=self.vraag_locatie_en_antwoord, args=(info,), daemon=True).start()

    def maak_schrijfbare_mappen(self):
        try:
            os.makedirs(self.TEMP_PDF_DIR, exist_ok=True)
        except Exception as fout:
            print(f"Tijdelijke map kon niet worden gemaakt: {fout}")

    def asset_pad(self, bestandsnaam):
        return os.path.join(ASSETS_DIR, bestandsnaam)

    def pictogram_pad(self, bestandsnaam):
        return os.path.join(PICTO_DIR, bestandsnaam)

    def laad_geluid(self, bestandsnaam):
        pad = self.asset_pad(bestandsnaam)
        if not os.path.exists(pad):
            print(f"Geluidsbestand niet gevonden: {pad}")
            return None
        try:
            return SoundLoader.load(pad)
        except Exception as fout:
            print(f"Geluidsbestand kon niet worden geladen: {fout}")
            return None

    def speel_geluid(self, geluid, herhalen=False):
        if geluid is not None:
            try:
                geluid.loop = herhalen
                geluid.stop()
                geluid.play()
            except Exception as fout:
                print(f"Geluid kon niet worden afgespeeld: {fout}")

    def stop_geluid(self, geluid):
        if geluid is not None:
            try:
                geluid.stop()
            except Exception as fout:
                print(f"Geluid kon niet worden gestopt: {fout}")

    def _update_rect(self, instance, value):
        self.bg_rect.pos = instance.pos
        self.bg_rect.size = instance.size

    def _update_label_text_size(self, instance, size):
        instance.text_size = size

    def update_progress_rects(self, obj, *args):
        self.bar_bg_rect.pos = obj.pos
        self.bar_bg_rect.size = obj.size
        breedte = (obj.value / obj.max) * obj.width if obj.max > 0 else 0
        self.bar_fill_rect.pos = obj.pos
        self.bar_fill_rect.size = (max(0, min(breedte, obj.width)), obj.height)

    def log_status(self, bericht):
        print(f"STATUS: {bericht}")
        if hasattr(self, "status_log"):
            Clock.schedule_once(lambda dt, tekst=str(bericht): setattr(self.status_log, "text", tekst))

    def update_ui(self, tekst, hex_bg, hex_txt, pic_string=None):
        def change(dt):
            self.centraal_label.text = str(tekst).upper()
            Animation(rgba=get_color_from_hex(hex_bg), duration=0.6).start(self.bg_color)
            Animation(color=get_color_from_hex(hex_txt), duration=0.6).start(self.centraal_label)
            self.pic_layout.clear_widgets()
            if pic_string:
                for naam in [x.strip() for x in pic_string.split(",") if x.strip()]:
                    pad = self.pictogram_pad(naam)
                    if os.path.exists(pad):
                        self.pic_layout.add_widget(Image(source=pad, allow_stretch=True))
                self.pic_layout.size_hint_y = 0.6
                self.centraal_label.size_hint_y = 0.4
            else:
                self.pic_layout.size_hint_y = 0.001
                self.centraal_label.size_hint_y = 1.0
        Clock.schedule_once(change)

    def start_intro_sequentie(self, dt):
        self.speel_geluid(self.intro_audio)
        animatie = Animation(opacity=1, duration=INTRO_DUUR, t="out_quad")
        animatie.bind(on_complete=self.activeer_spraak_systeem)
        animatie.start(self.centraal_label)

    def activeer_spraak_systeem(self, *args):
        threading.Thread(target=self.initialiseer_audio_en_loop, daemon=True).start()

    def assistent_spreekt(self, tekst):
        if platform == "android":
            print(
                f"[ANDROID TTS TEST]: {tekst}"
            )
            return

        if edge_tts is None:
            return
            bestandsnaam = os.path.join(self.DATA_DIR, f"spraak_{int(time.time() * 1000)}.mp3")
            try:
                asyncio.run(edge_tts.Communicate(tekst, "nl-NL-FennaNeural").save(bestandsnaam))
                geluid = SoundLoader.load(bestandsnaam)
                if geluid:
                    geluid.play()
                    while geluid.state == "play":
                        time.sleep(0.05)
            except Exception as fout:
                print(f"Spraakfout: {fout}")
            finally:
                if os.path.exists(bestandsnaam):
                    try:
                        os.remove(bestandsnaam)
                    except OSError:
                        pass

    def initialiseer_audio_en_loop(self):
        try:
            self.schoonmaak_bij_opstart()
            self.lab_database = self.laad_stoffen()
            threading.Thread(target=self.automatische_map_scanner, daemon=True).start()
            if platform == "android":
                self.log_status("ANDROID SPRAAKSERVICE START...")
                return
            self.log_status("SYSTEEM GEREED - LUISTEREND...")
            self.hoofd_loop()
        except Exception as fout:
            self.log_status(f"OPSTARTFOUT: {fout}")

    def hoofd_loop(self):
        if platform == "android":
            return
        if sr is None:
            self.log_status("SPRAAKHERKENNING NIET BESCHIKBAAR")
            return
        self.recognizer = sr.Recognizer()
        while True:
            try:
                with sr.Microphone() as source:
                    audio = self.recognizer.listen(source, timeout=None, phrase_time_limit=3)
                tekst = self.recognizer.recognize_google(audio, language="nl-NL").lower()
                if "chemie" in tekst or "chemi" in tekst:
                    self.speel_geluid(self.ping_sound)
            except sr.UnknownValueError:
                pass
            except Exception as fout:
                print(f"Spraakloopfout: {fout}")
                time.sleep(1)

    def set_locatie(self, locatie):
        self.gekozen_locatie = locatie
        self.keuze_event.set()

    def vraag_locatie_en_antwoord(self, info):
        self.systeem_bezet = True
        self.gekozen_locatie = None
        self.keuze_event.clear()
        self.update_ui("KIES LOCATIE", KLEUR_KEUZE, "#FFFFFF", info.get("pictogram", ""))
        Clock.schedule_once(lambda dt: Animation(pos_hint={"center_x": 0.5, "y": 0.1}, opacity=1, duration=0.5).start(self.btn_layout_locatie))
        if platform == "android":
            self.wacht_op_locatie = True
            self.huidige_spraak_info = info
        start = time.time()
        while not self.keuze_event.is_set() and time.time() - start < 15:
            time.sleep(0.1)
        locatie = self.gekozen_locatie or "lab"
        pics = info.get("pbm_pic_lab", "") if locatie == "lab" else info.get("pbm_pic_fabriek", "")
        self.update_ui(info.get("naam", "ONBEKENDE STOF"), KLEUR_LUISTEREN, "#FFFFFF", pics)
        time.sleep(3)
        self.wacht_op_locatie = False
        self.huidige_spraak_info = None
        self.systeem_bezet = False
        Clock.schedule_once(lambda dt: Animation(pos_hint={"center_x": 0.5, "y": -0.3}, opacity=0, duration=0.3).start(self.btn_layout_locatie))
        self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER)

    def start_nood_timer(self, info, minuten=15):
        self.nood_actief = True
        self.systeem_bezet = True
        self.timer_seconds = minuten * 60
        self.update_ui(f"NOODGEVAL\n{minuten}:00", KLEUR_NOOD, "#FFFFFF", info.get("pictogram", ""))
        self.progress.max = self.timer_seconds
        self.progress.value = self.timer_seconds
        self.progress.opacity = 1
        self.speel_geluid(self.alarm_sound, herhalen=True)
        if self.timer_event:
            self.timer_event.cancel()
        self.timer_event = Clock.schedule_interval(lambda dt: self._timer_tick(info), 1)
        Animation(pos_hint={"center_x": 0.3, "y": 0.05}, opacity=1, duration=0.5).start(self.btn_alarm_mute)
        Animation(pos_hint={"center_x": 0.7, "y": 0.05}, opacity=1, duration=0.5).start(self.btn_nood_stop)
        self.btn_alarm_mute.disabled = False
        self.btn_alarm_mute.text = "ALARM UIT"

    def _timer_tick(self, info):
        if not self.nood_actief:
            return False
        self.timer_seconds -= 1
        self.progress.value = self.timer_seconds
        minuten, seconden = divmod(self.timer_seconds, 60)
        self.centraal_label.text = f"NOODGEVAL\n{minuten:02d}:{seconden:02d}"
        if self.timer_seconds <= 0:
            self.stop_timer_voltooid()
            return False
        return True

    def stop_timer_voltooid(self):
        self.stop_geluid(self.alarm_sound)
        self.update_ui("KLAAR", "#27AE60", "#FFFFFF")

    def stop_noodprocedure(self, *args):
        self.nood_actief = False
        self.systeem_bezet = False
        if self.timer_event:
            self.timer_event.cancel()
            self.timer_event = None
        self.stop_geluid(self.alarm_sound)
        self.progress.opacity = 0
        Animation(pos_hint={"center_x": 0.3, "y": -0.2}, opacity=0, duration=0.5).start(self.btn_alarm_mute)
        Animation(pos_hint={"center_x": 0.7, "y": -0.2}, opacity=0, duration=0.5).start(self.btn_nood_stop)
        self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER)
        self.log_status("NOODPROCEDURE GESTOPT")

    def mute_alarm(self, instance):
        self.stop_geluid(self.alarm_sound)
        instance.text = "ALARM UITGEZET"
        instance.disabled = True

    def log_noodgeval(self, stof):
        try:
            nieuw = not os.path.exists(self.NOODLOG_PAD)
            with open(self.NOODLOG_PAD, "a", encoding="utf-8", newline="") as bestand:
                schrijver = csv.writer(bestand)
                if nieuw:
                    schrijver.writerow(["datum_tijd", "stof"])
                schrijver.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), stof])
        except Exception as fout:
            print(f"Noodgeval kon niet worden gelogd: {fout}")

    def toon_pdf_in_app(self, pdf_pad):
        self.pdf_is_pauze = False
        self.systeem_bezet = True
        try:
            reader = PdfReader(pdf_pad)
            self.pdf_paginas_tekst = [p.extract_text() or "Geen tekst op deze pagina." for p in reader.pages]
        except Exception as fout:
            print(f"PDF kon niet worden geladen: {fout}")
            self.pdf_paginas_tekst = ["Kan PDF-tekst niet laden."]
        self.totaal_pdf_paginas = max(1, len(self.pdf_paginas_tekst))
        if not hasattr(self, "pdf_text_label"):
            self.pdf_text_label = Label(font_name=GEBRUIK_FONT, font_size="22sp", color=get_color_from_hex(KLEUR_TEKST_DONKER), size_hint_y=None, halign="left", valign="top", padding=(20, 20))
            self.pdf_text_label.bind(width=lambda i, w: setattr(i, "text_size", (max(w - 40, 100), None)))
            self.pdf_text_label.bind(texture_size=lambda i, s: setattr(i, "height", s[1] + 40))
            self.pdf_scroll_view.add_widget(self.pdf_text_label)
        self.pdf_scroll_view.opacity = 1
        self.scroll_pagina(0, self.totaal_pdf_paginas)

    def handmatige_scroll_detectie(self, instance, touch):
        self.pdf_is_pauze = True
        return False

    def scroll_pagina(self, index, totaal):
        if not 0 <= index < totaal:
            return
        self.huidige_pdf_index = index
        self.pdf_text_label.text = self.pdf_paginas_tekst[index]
        self.pdf_scroll_view.scroll_y = 1.0
        self.ui.opacity = 0

    def wissel_pagina(self, richting):
        self.scroll_pagina(self.huidige_pdf_index + richting, self.totaal_pdf_paginas)

    def toggle_pauze(self, instance):
        self.pdf_is_pauze = not self.pdf_is_pauze

    def sluit_pdf(self, *args):
        self.systeem_bezet = False
        self.pdf_scroll_view.opacity = 0
        self.ui.opacity = 1
        self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER)

    def automatische_map_scanner(self):
        while True:
            time.sleep(5)
            if not self.nood_actief:
                self.lab_database.update(self.laad_stoffen())

    def normaliseer_stofnaam(self, tekst):
        return re.sub(r"[^a-z0-9]+", "", str(tekst).lower().strip())

    def analyseer_msds_pdf(self, pdf_pad):
        try:
            reader = PdfReader(pdf_pad)
            tekst = "\n".join(p.extract_text() or "" for p in reader.pages)
            laag = tekst.lower()
            pics = []
            mapping = {"ghs01":"explosief.png","ghs02":"Brandbaar.png","ghs03":"oxiderend.png","ghs04":"gassen.png","ghs05":"Corrosief.png","ghs06":"giftig.png","ghs07":"!.png","ghs08":"ongezond.png","ghs09":"milieu.png"}
            for code, pic in mapping.items():
                if code in laag:
                    pics.append(pic)
            return {
                "naam": Path(pdf_pad).stem,
                "pbm_lab": "Draag de voorgeschreven beschermingsmiddelen.",
                "pbm_fabriek": "Draag de voorgeschreven beschermingsmiddelen.",
                "pbm_pic_lab": "", "pbm_pic_fabriek": "",
                "pictogram": ",".join(pics),
                "n_ogen": "Bij contact met de ogen, direct spoelen met overvloedig water en een arts raadplegen.",
                "msds": Path(pdf_pad).name,
                "gevaren": "Zie het veiligheidsblad voor de specifieke gevaren."
            }
        except Exception as fout:
            print(f"Fout bij uitlezen PDF {pdf_pad}: {fout}")
            return None

    def laad_stoffen(self):
        database = {}
        if os.path.exists(STOFFEN_CSV):
            try:
                with open(STOFFEN_CSV, "r", encoding="utf-8-sig") as bestand:
                    eerste = bestand.readline()
                    bestand.seek(0)
                    for rij in csv.DictReader(bestand, delimiter=";" if ";" in eerste else ","):
                        schoon = {str(k).strip().lower(): str(v).strip() for k, v in rij.items() if k and v is not None}
                        naam = schoon.get("stof", next(iter(schoon.values()), ""))
                        if naam:
                            database[self.normaliseer_stofnaam(naam)] = {
                                "naam": naam, "pbm_lab": schoon.get("pbm_lab", ""),
                                "pbm_fabriek": schoon.get("pbm_fabriek", ""),
                                "pbm_pic_lab": schoon.get("pbm_pic_lab", ""),
                                "pbm_pic_fabriek": schoon.get("pbm_pic_fabriek", ""),
                                "pictogram": schoon.get("pictogram", ""),
                                "n_ogen": next((v for k, v in schoon.items() if "ogen" in k), ""),
                                "msds": schoon.get("msds", ""),
                                "gevaren": schoon.get("gevaren", "Er zijn geen specifieke gevaren bekend.")
                            }
            except Exception as fout:
                print(f"Fout bij laden CSV: {fout}")
        if os.path.exists(MSDS_DIR):
            for naam in os.listdir(MSDS_DIR):
                if naam.lower().endswith(".pdf"):
                    sid = self.normaliseer_stofnaam(os.path.splitext(naam)[0])
                    if sid not in database:
                        data = self.analyseer_msds_pdf(os.path.join(MSDS_DIR, naam))
                        if data:
                            database[sid] = data
        print(f"Aantal geladen stoffen: {len(database)}")
        return database

    def vind_beste_stof(self, opdracht):
        if not opdracht or not self.lab_database:
            return None
        woorden = re.findall(r"[a-zA-Z0-9À-ÿ]+", opdracht.lower())
        ids = list(self.lab_database.keys())
        combinatie = self.normaliseer_stofnaam(" ".join(woorden))
        for sid in ids:
            if sid and (sid in combinatie or combinatie in sid):
                return sid
        for woord in woorden:
            matches = difflib.get_close_matches(self.normaliseer_stofnaam(woord), ids, n=1, cutoff=0.6)
            if matches:
                return matches[0]
        return None

    def lees_gevaren_voor(self, info):
        self.systeem_bezet = True
        self.update_ui(f"GEVAREN: {info.get('naam', '')}", "#FF4500", "#FFFFFF", info.get("pictogram", ""))
        time.sleep(4)
        self.systeem_bezet = False
        self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER)

    def open_msds(self, info):
        pdf = info.get("msds", "")
        pad = os.path.join(MSDS_DIR, pdf)
        if pdf and os.path.exists(pad):
            Clock.schedule_once(lambda dt: self.toon_pdf_in_app(pad))

    def schoonmaak_bij_opstart(self):
        try:
            for naam in os.listdir(self.TEMP_PDF_DIR):
                pad = os.path.join(self.TEMP_PDF_DIR, naam)
                if os.path.isfile(pad):
                    os.remove(pad)
        except Exception as fout:
            print(f"Opschoonfout: {fout}")


if __name__ == "__main__":
    ChemieApp().run()
