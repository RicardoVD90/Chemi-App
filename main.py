import os
print("========== VERSIE 22-09-2026 PDF-AUTO-SCROLL ==========")
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
from pdf_renderer import AndroidPdfRenderCache

try:
    import edge_tts
    print("[EDGE TTS IMPORT]: MODULE SUCCESVOL GELADEN")
except Exception as fout:
    print(f"[EDGE TTS IMPORT FOUT]: {type(fout).__name__}: {fout}")
    edge_tts = None

if platform != "android":
    try:
        import speech_recognition as sr
    except ImportError:
        sr = None
else:
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
        self.pdf_open = False
        self.pdf_scroll_event = None
        self.pdf_scroll_stap = 0.0008
        self.gekozen_locatie = None
        self.keuze_event = threading.Event()
        self.huidige_pdf_index = 0
        self.totaal_pdf_paginas = 0
        self.pdf_paginas_tekst = []
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
        self.RENDERED_MSDS_DIR = os.path.join(self.DATA_DIR, "rendered_msds")
        self.pdf_renderer = AndroidPdfRenderCache(
        self.RENDERED_MSDS_DIR,schaal=1.5,logger=print)
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
        self.centraal_label = Label(text="CHEMI", font_name=GEBRUIK_FONT, font_size="100sp", opacity=0,
                                    bold=True, halign="center", valign="middle",
                                    color=get_color_from_hex(KLEUR_TEKST_DONKER))
        self.centraal_label.bind(size=self._update_label_text_size)
        self.status_log = Label(text="OPSTARTEN...", font_size="14sp", size_hint=(1, 0.1),
                                color=get_color_from_hex("#7F8C8D"), halign="center", valign="middle")
        self.status_log.bind(size=self._update_label_text_size)
        self.progress = ProgressWidget(size_hint=(0.6, 0.01), pos_hint={"center_x": 0.5, "y": 0.15}, opacity=0)
        with self.progress.canvas:
            self.bg_bar_color = Color(rgba=get_color_from_hex("#BDC3C7"))
            self.bar_bg_rect = Rectangle(pos=self.progress.pos, size=self.progress.size)
            self.fill_bar_color = Color(rgba=get_color_from_hex("#FFFFFF"))
            self.bar_fill_rect = Rectangle(pos=self.progress.pos, size=self.progress.size)
        self.progress.bind(pos=self.update_progress_rects, size=self.update_progress_rects,
                           value=self.update_progress_rects, max=self.update_progress_rects)
        self.ui.add_widget(self.pic_layout)
        self.ui.add_widget(self.centraal_label)
        self.ui.add_widget(self.status_log)
        self.root_layout.add_widget(self.ui)
        self.root_layout.add_widget(self.progress)

        self.btn_layout_locatie = BoxLayout(orientation="horizontal", size_hint=(None, None), size=(500, 75),
                                             pos_hint={"center_x": 0.5, "y": -0.3}, spacing=40, opacity=0)
        stijl = {"background_normal": "", "font_size": "22sp", "bold": True}
        self.btn_lab = Button(text="LABORATORIUM", background_color=get_color_from_hex(KLEUR_TEKST_DONKER), **stijl)
        self.btn_fabriek = Button(text="FABRIEK", background_color=get_color_from_hex(KLEUR_TEKST_DONKER), **stijl)
        self.btn_lab.bind(on_release=lambda knop: self.set_locatie("lab"))
        self.btn_fabriek.bind(on_release=lambda knop: self.set_locatie("fabriek"))
        self.btn_layout_locatie.add_widget(self.btn_lab)
        self.btn_layout_locatie.add_widget(self.btn_fabriek)
        self.root_layout.add_widget(self.btn_layout_locatie)

        self.btn_nood_stop = Button(text="STOP NOODPROCEDURE", size_hint=(None, None), size=(400, 100),
                                     pos_hint={"center_x": 0.7, "y": -0.2}, background_normal="",
                                     background_color=(1, 1, 1, 1), color=get_color_from_hex(KLEUR_NOOD),
                                     bold=True, font_size="24sp", opacity=0)
        self.btn_nood_stop.bind(on_release=self.stop_noodprocedure)
        self.root_layout.add_widget(self.btn_nood_stop)
        self.btn_alarm_mute = Button(text="ALARM\nDEMPEN", size_hint=(None, None), size=(220, 100),
                                      pos_hint={"center_x": 0.3, "y": -0.2}, background_normal="",
                                      background_color=get_color_from_hex(KLEUR_MUTE),
                                      color=get_color_from_hex(KLEUR_TEKST_WIT), bold=True,
                                      halign="center", font_size="20sp", opacity=0)
        self.btn_alarm_mute.bind(on_release=self.mute_alarm)
        self.root_layout.add_widget(self.btn_alarm_mute)

        self.pdf_scroll_view = ScrollView(size_hint=(0.9, 0.80), pos_hint={"center_x": 0.5, "center_y": 0.58},
                                          do_scroll_x=False, do_scroll_y=True, opacity=0)
        self.pdf_scroll_view.bind(on_scroll_start=self.handmatige_scroll_detectie)
        self.pdf_pagina_label = Label(
            text="Pagina 1 / 1",
            size_hint=(None, None),
            size=(250, 50),
            pos_hint={"right": 0.98, "top": 0.98},
            font_size="20sp",
            bold=True,
            color=get_color_from_hex(KLEUR_TEKST_DONKER),
            opacity=0
        )
        
        self.root_layout.add_widget(
            self.pdf_pagina_label
        )
        self.pdf_controls = BoxLayout(orientation="horizontal", size_hint=(None, None), size=(550, 110),
                                      pos_hint={"center_x": 0.52, "y": -0.2}, padding=10, spacing=20, opacity=0)
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

        self.pdf_pagina_paden = []

        Clock.schedule_once(self.start_intro_sequentie, 0.5)
        return self.root_layout

    def on_start(self):
        if platform == "android":
            self.vraag_android_permissies()
            Clock.schedule_once(self.start_android_listener, 10.0)

    def on_stop(self):
        if platform == "android" and self.android_listener is not None:
            try:
                self.android_listener.stop()
            except Exception as fout:
                print(f"Luisterservice kon niet netjes stoppen: {fout}")

    def vraag_android_permissies(self):
        if request_permissions is None or Permission is None:
            return
        permissies = [Permission.RECORD_AUDIO]
        if hasattr(Permission, "READ_EXTERNAL_STORAGE"):
            permissies.append(Permission.READ_EXTERNAL_STORAGE)
        if hasattr(Permission, "WRITE_EXTERNAL_STORAGE"):
            permissies.append(Permission.WRITE_EXTERNAL_STORAGE)
        request_permissions(permissies)

    def start_android_listener(self, dt=None):
        if platform != "android" or AndroidContinuousListener is None:
            return
        if self.android_listener is None:
            self.android_listener = AndroidContinuousListener(on_text=self.verwerk_android_spraak,
                                                               on_status=self.android_luisterstatus,
                                                               on_error=self.android_luisterfout,
                                                               language="nl-NL")
        self.android_listener.start()

    def android_luisterstatus(self, status):
        self.android_spraak_actief = status in ("MICROFOON ACTIEF - ZEG CHEMI", "MICROFOON START...",
                                                 "SPRAAK GEHOORD", "SPRAAK VERWERKEN...")
        self.log_status(status)

    def android_luisterfout(self, fout):
        self.android_spraak_actief = False
        self.log_status(f"WAARSCHUWING: {fout}")

    def verwerk_pdf_spraakopdracht(self, tekst):
        if not self.pdf_open:
            return False
        tekst = str(tekst).lower().strip()
        if any(x in tekst for x in ["stop pdf", "sluit pdf", "pdf sluiten", "sluit document", "terug naar chemi"]):
            print("[PDF SPRAAK]: PDF SLUITEN")
            Clock.schedule_once(lambda dt: self.sluit_pdf())
            return True
        if any(x in tekst for x in ["volgende pagina", "pagina verder", "volgende bladzijde"]):
            print("[PDF SPRAAK]: VOLGENDE PAGINA")
            Clock.schedule_once(lambda dt: self.wissel_pagina(1))
            return True
        if any(x in tekst for x in ["vorige pagina", "pagina terug", "vorige bladzijde"]):
            print("[PDF SPRAAK]: VORIGE PAGINA")
            Clock.schedule_once(lambda dt: self.wissel_pagina(-1))
            return True
        if any(x in tekst for x in ["pauze", "pauzeer", "stop scrollen", "scrollen stoppen"]):
            Clock.schedule_once(lambda dt: self.pauzeer_pdf_scroll())
            return True
        if any(x in tekst for x in ["hervat", "ga door", "verder scrollen", "scrollen hervatten"]):
            Clock.schedule_once(lambda dt: self.hervat_pdf_scroll())
            return True
        return False

    def verwerk_android_spraak(self, gesproken_tekst):
        try:
            tekst = str(gesproken_tekst).lower().strip()
            print(f"[ANDROID GEHOORD]: {tekst}")
            if not tekst:
                return
            if self.verwerk_pdf_spraakopdracht(tekst):
                return
            if self.nood_actief:
                if any(x in tekst for x in ["stop noodprocedure", "stop alarm", "alarm stoppen"]):
                    self.stop_noodprocedure()
                return
            if self.wacht_op_locatie:
                if "laboratorium" in tekst or tekst == "lab" or "het lab" in tekst:
                    self.wacht_op_locatie = False
                    self.set_locatie("lab")
                    return
                if "fabriek" in tekst or "productie" in tekst or "de hal" in tekst:
                    self.wacht_op_locatie = False
                    self.set_locatie("fabriek")
                    return
            noodzinnen = ["noodgeval", "help", "in mijn ogen", "in de ogen", "vloeistof in ogen",
                          "vloeistof in mijn ogen", "chemische stof in ogen", "chemische stof in mijn ogen",
                          "ogen spoelen", "oog spoelen", "spoel mijn ogen", "brand in mijn ogen"]
            if any(x in tekst for x in noodzinnen):
                nu = time.time()
                if nu - self.laatste_noodactie < 5:
                    return
                self.laatste_noodactie = nu
                self.wacht_op_opdracht = False
                self.verwerk_android_noodgeval(tekst)
                return
            if self.wacht_op_opdracht:
                self.wacht_op_opdracht = False
                self.verwerk_android_opdracht(tekst)
                return
            if "chemi" in tekst or "chemie" in tekst:
                opdracht = tekst.replace("chemie", "", 1).replace("chemi", "", 1).strip(" ,.!?")
                if opdracht:
                    self.verwerk_android_opdracht(opdracht)
                    return
                self.wacht_op_opdracht = True
                self.update_ui("WAT KAN IK VOOR U DOEN?", KLEUR_VRAAG, KLEUR_TEKST_DONKER)
                self.speel_geluid(self.ping_sound)
                self.assistent_spreekt("Wat kan ik voor u doen?")
                Clock.schedule_once(self.reset_wachten_op_opdracht, 10)
        except Exception as fout:
            print(f"[ANDROID FOUT VERWERK_SPRAAK]: {type(fout).__name__}: {fout}")

    def reset_wachten_op_opdracht(self, dt=None):
        if self.wacht_op_opdracht:
            self.wacht_op_opdracht = False
            if not self.nood_actief:
                self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER)

    def verwerk_android_noodgeval(self, tekst):
        stof_id = self.vind_beste_stof(tekst)
        info = self.lab_database.get(stof_id) if stof_id else None
        if not info:
            info = {"naam": "ONBEKENDE STOF", "pictogram": "", "n_ogen": "Begin direct met spoelen.",
                    "pbm_lab": "", "pbm_fabriek": "", "pbm_pic_lab": "", "pbm_pic_fabriek": "",
                    "msds": "", "gevaren": ""}
        self.log_noodgeval(info["naam"])
        self.start_nood_timer(info, 15)

    def verwerk_android_opdracht(self, tekst):
        self.log_status(f"OPDRACHT GEHOORD: {tekst}")
        stof_id = self.vind_beste_stof(tekst)
        print(f"[ANDROID STOFMATCH]: {stof_id}")
        if not stof_id:
            self.update_ui("STOF NIET HERKEND", KLEUR_VRAAG, KLEUR_TEKST_DONKER)
            Clock.schedule_once(lambda dt: self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER), 3)
            return
        info = self.lab_database[stof_id]
        if any(w in tekst for w in ["oog", "ogen", "spoelen", "nood", "help"]):
            self.start_nood_timer(info, 15)
        elif any(w in tekst for w in ["gevaar", "gevaren", "risico", "gevaarlijk"]):
            threading.Thread(target=self.lees_gevaren_voor, args=(info,), daemon=True).start()
        elif any(w in tekst for w in ["pdf", "msds", "veiligheidsblad", "veiligheidsinformatieblad", "blad"]):
            self.open_msds(info)
        else:
            threading.Thread(target=self.vraag_locatie_en_antwoord, args=(info,), daemon=True).start()

    def maak_schrijfbare_mappen(self):
        os.makedirs(
            self.TEMP_PDF_DIR,
            exist_ok=True
        )
    
        os.makedirs(
            self.RENDERED_MSDS_DIR,
            exist_ok=True
        )

    def asset_pad(self, naam): return os.path.join(ASSETS_DIR, naam)
    def pictogram_pad(self, naam): return os.path.join(PICTO_DIR, naam)

    def laad_geluid(self, naam):
        pad = self.asset_pad(naam)
        return SoundLoader.load(pad) if os.path.exists(pad) else None

    def speel_geluid(self, geluid, herhalen=False):
        if geluid:
            geluid.loop = herhalen
            geluid.stop()
            geluid.play()

    def stop_geluid(self, geluid):
        if geluid:
            geluid.stop()

    def _update_rect(self, instance, value):
        self.bg_rect.pos = instance.pos
        self.bg_rect.size = instance.size

    def _update_label_text_size(self, instance, size): instance.text_size = size

    def update_progress_rects(self, obj, *args):
        self.bar_bg_rect.pos, self.bar_bg_rect.size = obj.pos, obj.size
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
        anim = Animation(opacity=1, duration=INTRO_DUUR, t="out_quad")
        anim.bind(on_complete=self.activeer_spraak_systeem)
        anim.start(self.centraal_label)

    def activeer_spraak_systeem(self, *args):
        threading.Thread(target=self.initialiseer_audio_en_loop, daemon=True).start()

    def assistent_spreekt(self, tekst):
        if platform == "android":
            try:
                from jnius import autoclass
                TextToSpeech = autoclass("android.speech.tts.TextToSpeech")
                HashMap = autoclass("java.util.HashMap")
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                Locale = autoclass("java.util.Locale")
                tts = TextToSpeech(PythonActivity.mActivity, None)
                tts.setLanguage(Locale("nl", "NL"))
                tts.speak(str(tekst), TextToSpeech.QUEUE_FLUSH, HashMap())
                print(f"[ANDROID TTS]: {tekst}")
            except Exception as fout:
                print(f"[ANDROID TTS FOUT]: {type(fout).__name__}: {fout}")
            return
        if edge_tts is None:
            return
        bestand = os.path.join(self.DATA_DIR, f"spraak_{int(time.time()*1000)}.mp3")
        try:
            asyncio.run(edge_tts.Communicate(str(tekst), "nl-NL-FennaNeural").save(bestand))
            geluid = SoundLoader.load(bestand)
            if geluid:
                geluid.play()
                while geluid.state == "play": time.sleep(0.05)
        finally:
            if os.path.exists(bestand): os.remove(bestand)

    def initialiseer_audio_en_loop(self):
        try:
            self.schoonmaak_bij_opstart()
            self.lab_database = self.laad_stoffen()
    
            if platform == "android":
                threading.Thread(
                    target=self.pdf_renderer.render_alle,
                    args=(MSDS_DIR,),
                    daemon=True
                ).start()
    
                self.log_status(
                    "ANDROID SPRAAKSERVICE START..."
                )
    
                return
    
            self.log_status(
                "SYSTEEM GEREED - LUISTEREND..."
            )
    
            self.hoofd_loop()
    
        except Exception as fout:
            print(
                "[OPSTARTFOUT\]: "
                f"{type(fout).__name__}: {fout}"
            )
    
            self.log_status(
                f"OPSTARTFOUT: {fout}"
            )

    def hoofd_loop(self):
        if platform == "android" or sr is None: return
        self.recognizer = sr.Recognizer()
        while True:
            try:
                with sr.Microphone() as source:
                    audio = self.recognizer.listen(source, timeout=None, phrase_time_limit=3)
                tekst = self.recognizer.recognize_google(audio, language="nl-NL").lower()
                if "chemie" in tekst: self.speel_geluid(self.ping_sound)
            except Exception:
                time.sleep(1)

    def set_locatie(self, locatie):
        self.gekozen_locatie = locatie
        self.keuze_event.set()

    def vraag_locatie_en_antwoord(self, info):
        self.systeem_bezet = True
        self.gekozen_locatie = None
        self.keuze_event.clear()
    
        self.update_ui(
            "KIES LOCATIE",
            KLEUR_KEUZE,
            "#FFFFFF",
            info.get("pictogram", "")
        )
    
        Clock.schedule_once(
            lambda dt: Animation(
                pos_hint={
                    "center_x": 0.5,
                    "y": 0.1
                },
                opacity=1,
                duration=0.5
            ).start(
                self.btn_layout_locatie
            )
        )
    
        if platform == "android":
            self.wacht_op_locatie = True
            self.huidige_spraak_info = info
    
        self.assistent_spreekt(
            "Is dit voor het laboratorium "
            "of voor de fabriek?"
        )
    
        start = time.time()
    
        while (
            not self.keuze_event.is_set()
            and time.time() - start < 15
        ):
            time.sleep(0.1)
    
        locatie = (
            self.gekozen_locatie
            or "lab"
        )
    
        if locatie == "lab":
            locatie_naam = "laboratorium"
    
            pbm_tekst = info.get(
                "pbm_lab",
                ""
            )
    
            pbm_pics = info.get(
                "pbm_pic_lab",
                ""
            )
    
        else:
            locatie_naam = "fabriek"
    
            pbm_tekst = info.get(
                "pbm_fabriek",
                ""
            )
    
            pbm_pics = info.get(
                "pbm_pic_fabriek",
                ""
            )
    
        if not pbm_tekst:
            pbm_tekst = (
                "De vereiste persoonlijke "
                "beschermingsmiddelen konden niet "
                "betrouwbaar worden vastgesteld. "
                "Controleer de geldende PBM matrix, "
                "werkvergunning en werkinstructie."
            )
    
        print(
            "[PBM RESULTAAT]: "
            f"STOF={info.get('naam', '')}; "
            f"LOCATIE={locatie_naam}; "
            f"TEKST={pbm_tekst}; "
            f"PICTOGRAMMEN={pbm_pics or 'GEEN'}"
        )
    
        self.update_ui(
            info.get(
                "naam",
                "ONBEKENDE STOF"
            ),
            KLEUR_LUISTEREN,
            "#FFFFFF",
            pbm_pics
        )
    
        self.assistent_spreekt(
            f"De persoonlijke beschermingsmiddelen "
            f"voor {info.get('naam', 'deze stof')} "
            f"in het {locatie_naam} zijn: "
            f"{pbm_tekst}"
        )
    
        # Wacht iets langer zodat de PBM’s zichtbaar blijven.
        time.sleep(8)
    
        self.wacht_op_locatie = False
        self.huidige_spraak_info = None
        self.systeem_bezet = False
    
        Clock.schedule_once(
            lambda dt: Animation(
                pos_hint={
                    "center_x": 0.5,
                    "y": -0.3
                },
                opacity=0,
                duration=0.3
            ).start(
                self.btn_layout_locatie
            )
        )
    
        self.update_ui(
            "CHEMI",
            BG_STANDBY,
            KLEUR_TEKST_DONKER
        )

    def start_nood_timer(self, info, minuten=15):
        self.nood_actief = self.systeem_bezet = True
        self.timer_seconds = minuten * 60
        self.update_ui(f"NOODGEVAL\n{minuten}:00", KLEUR_NOOD, "#FFFFFF", info.get("pictogram", ""))
        self.progress.max = self.progress.value = self.timer_seconds
        self.progress.opacity = 1
        self.speel_geluid(self.alarm_sound, True)
        if self.timer_event: self.timer_event.cancel()
        self.timer_event = Clock.schedule_interval(lambda dt: self._timer_tick(info), 1)

    def _timer_tick(self, info):
        if not self.nood_actief: return False
        self.timer_seconds -= 1
        self.progress.value = self.timer_seconds
        m, s = divmod(self.timer_seconds, 60)
        self.centraal_label.text = f"NOODGEVAL\n{m:02d}:{s:02d}"
        if self.timer_seconds <= 0:
            self.stop_noodprocedure()
            return False
        return True

    def stop_noodprocedure(self, *args):
        self.nood_actief = self.systeem_bezet = False
        if self.timer_event:
            self.timer_event.cancel(); self.timer_event = None
        self.stop_geluid(self.alarm_sound)
        self.progress.opacity = 0
        self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER)

    def mute_alarm(self, instance):
        self.stop_geluid(self.alarm_sound)
        instance.text = "ALARM UITGEZET"
        instance.disabled = True

    def log_noodgeval(self, stof):
        nieuw = not os.path.exists(self.NOODLOG_PAD)
        with open(self.NOODLOG_PAD, "a", encoding="utf-8", newline="") as bestand:
            schrijver = csv.writer(bestand)
            if nieuw: schrijver.writerow(["datum_tijd", "stof"])
            schrijver.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), stof])

    # PDF VIEWER
    def toon_pdf_in_app(self, pdf_pad, pagina_paden):
        self.pdf_open = True
        self.pdf_is_pauze = False
        self.systeem_bezet = True
        self.huidige_pdf_index = 0
        self.pdf_pagina_paden = list(pagina_paden)
        self.totaal_pdf_paginas = len(self.pdf_pagina_paden)
    
        if not hasattr(self, "pdf_page_image"):
            self.pdf_page_image = Image(
                source="",
                size_hint_y=None,
                allow_stretch=True,
                keep_ratio=True
            )
            self.pdf_page_image.bind(texture=self._pdf_texture_veranderd)
            self.pdf_page_image.bind(width=self._pdf_breedte_veranderd)
            self.pdf_scroll_view.add_widget(self.pdf_page_image)
    
        self.ui.opacity = 0
        self.pdf_scroll_view.opacity = 1
        Animation(
            pos_hint={"center_x": 0.52, "y": 0.02},
            opacity=1,
            duration=0.4
        ).start(self.pdf_controls)
        self.scroll_pagina(0, self.totaal_pdf_paginas)
        self.start_pdf_auto_scroll()

    def _pdf_texture_veranderd(self, instance, texture):
        if texture and texture.width > 0:
            instance.height = instance.width * texture.height / texture.width

    def _pdf_breedte_veranderd(self, instance, breedte):
        if instance.texture and instance.texture.width > 0:
            instance.height = breedte * instance.texture.height / instance.texture.width

    def scroll_pagina(self, index, totaal):
        if not self.pdf_open or not 0 <= index < totaal:
            return
        self.huidige_pdf_index = index
        self.pdf_page_image.source = self.pdf_pagina_paden[index]
        self.pdf_page_image.reload()
        self.pdf_scroll_view.scroll_y = 1.0
        print(f"[PDF]: PAGINA {index + 1}/{totaal} GETOOND")

    def start_pdf_auto_scroll(self):
        if not self.pdf_open: return
        if self.pdf_scroll_event: self.pdf_scroll_event.cancel()
        self.pdf_scroll_event = Clock.schedule_interval(self.auto_scroll_pdf, 0.05)
        print("[PDF]: AUTOMATISCH SCROLLEN GESTART")

    def auto_scroll_pdf(self, dt):
        if not self.pdf_open: return False
        if self.pdf_is_pauze: return True
        nieuwe = self.pdf_scroll_view.scroll_y - self.pdf_scroll_stap
        if nieuwe > 0:
            self.pdf_scroll_view.scroll_y = nieuwe
            return True
        volgende = self.huidige_pdf_index + 1
        if volgende < self.totaal_pdf_paginas:
            self.scroll_pagina(
                volgende,
                self.totaal_pdf_paginas
            )
        else:
            print(
                "[PDF\]: EINDE DOCUMENT - SLUITEN"
            )
        
            Clock.schedule_once(
                lambda dt: self.sluit_pdf(),
                1
            )
        return True

    def pauzeer_pdf_scroll(self):
        if not self.pdf_open: return
        self.pdf_is_pauze = True
        self.btn_pauze.background_normal = self.asset_pad("verder_knop.png")
        print("[PDF]: SCROLLEN GEPAUZEERD")

    def hervat_pdf_scroll(self):
        if not self.pdf_open: return
        self.pdf_is_pauze = False
        self.btn_pauze.background_normal = self.asset_pad("pauze_knop.png")
        if not self.pdf_scroll_event: self.start_pdf_auto_scroll()
        print("[PDF]: SCROLLEN HERVAT")

    def handmatige_scroll_detectie(self, instance, touch):
        if self.pdf_open:
            self.pauzeer_pdf_scroll()
            print("[PDF]: HANDMATIGE SWIPE GEDETECTEERD")
        return False

    def wissel_pagina(self, richting):
        if not self.pdf_open: return
        nieuw = self.huidige_pdf_index + richting
        if 0 <= nieuw < self.totaal_pdf_paginas:
            self.scroll_pagina(nieuw, self.totaal_pdf_paginas)

    def toggle_pauze(self, instance):
        self.hervat_pdf_scroll() if self.pdf_is_pauze else self.pauzeer_pdf_scroll()

    def sluit_pdf(self, *args):
        print("[PDF]: PDF-VIEWER SLUITEN")
        self.pdf_open = False
        self.pdf_is_pauze = True
        self.systeem_bezet = False
        if self.pdf_scroll_event:
            self.pdf_scroll_event.cancel(); self.pdf_scroll_event = None
        Animation(pos_hint={"center_x": 0.52, "y": -0.2}, opacity=0, duration=0.4).start(self.pdf_controls)
        Animation(opacity=0, duration=0.4).start(self.pdf_scroll_view)
        Animation(opacity=1, duration=0.4).start(self.ui)
        self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER)

    def automatische_map_scanner(self): pass

    def normaliseer_stofnaam(self, tekst):
        return re.sub(r"[^a-z0-9]+", "", str(tekst).lower().strip())
        
    def extraheer_rubriek(
        self,
        tekst,
        nummer,
        volgend_nummer
    ):
        """
        Probeert één rubriek van een veiligheidsblad te isoleren.
        Ondersteunt Nederlandse en Engelse benamingen.
        """
    
        start_patronen = [
            rf"(rubriek|sectie|section|hoofdstuk)\s*{nummer}\b",
            rf"(^|\n)\s*{nummer}\s*[\.\-:]",
        ]
    
        eind_patronen = [
            rf"(rubriek|sectie|section|hoofdstuk)\s*{volgend_nummer}\b",
            rf"(^|\n)\s*{volgend_nummer}\s*[\.\-:]",
        ]
    
        start_match = None
    
        for patroon in start_patronen:
            start_match = re.search(
                patroon,
                tekst,
                flags=re.IGNORECASE | re.MULTILINE
            )
    
            if start_match:
                break
    
        if not start_match:
            return ""
    
        eind_match = None
    
        for patroon in eind_patronen:
            eind_match = re.search(
                patroon,
                tekst[start_match.end():],
                flags=re.IGNORECASE | re.MULTILINE
            )
    
            if eind_match:
                break
    
        if eind_match:
            eindpositie = (
                start_match.end()
                + eind_match.start()
            )
    
            return tekst[
                start_match.start():eindpositie
            ]
    
        return tekst[start_match.start():]
    
    
    def voeg_uniek_toe(self, lijst, waarde):
        if waarde and waarde not in lijst:
            lijst.append(waarde)
    def analyseer_msds_pdf(self, pdf_pad):
        """
        Analyseert automatisch:
        - rubriek 2: gevaren en GHS-pictogrammen;
        - rubriek 4: oogspoelinformatie;
        - rubriek 8: PBM's en PBM-pictogrammen.
    
        Gebruikt pypdf en werkt daardoor ook in de Android-APK.
        """
    
        try:
            print(
                "[MSDS ANALYSE\]: START "
                f"{os.path.basename(pdf_pad)}"
            )
    
            reader = PdfReader(pdf_pad)
    
            tekst_delen = []
    
            for pagina_nummer, pagina in enumerate(
                reader.pages,
                1
            ):
                try:
                    pagina_tekst = (
                        pagina.extract_text()
                        or ""
                    )
    
                    tekst_delen.append(
                        pagina_tekst
                    )
    
                except Exception as fout:
                    print(
                        "[MSDS ANALYSE WAARSCHUWING\]: "
                        f"pagina {pagina_nummer}: {fout}"
                    )
    
            volledige_tekst = "\n".join(
                tekst_delen
            )
    
            tekst_low = volledige_tekst.lower()
    
            stofnaam = Path(
                pdf_pad
            ).stem.strip()
    
            rubriek_2 = self.extraheer_rubriek(
                tekst_low,
                2,
                3
            )
    
            rubriek_4 = self.extraheer_rubriek(
                tekst_low,
                4,
                5
            )
    
            rubriek_8 = self.extraheer_rubriek(
                tekst_low,
                8,
                9
            )
    
            print(
                "[MSDS ANALYSE\]: "
                f"R2={'JA' if rubriek_2 else 'NEE'}, "
                f"R4={'JA' if rubriek_4 else 'NEE'}, "
                f"R8={'JA' if rubriek_8 else 'NEE'}"
            )
    
            # -----------------------------------
            # GEVARENPICTOGRAMMEN UIT RUBRIEK 2
            # -----------------------------------
    
            gevonden_gevaren_pics = []
    
            ghs_mapping = {
                "ghs01": "explosief.png",
                "ghs02": "Brandbaar.png",
                "ghs03": "oxiderend.png",
                "ghs04": "gassen.png",
                "ghs05": "Corrosief.png",
                "ghs06": "giftig.png",
                "ghs07": "!.png",
                "ghs08": "ongezond.png",
                "ghs09": "milieu.png",
            }
    
            zoekgebied_gevaren = (
                rubriek_2
                if rubriek_2
                else tekst_low
            )
    
            for ghs_code, bestandsnaam in (
                ghs_mapping.items()
            ):
                if ghs_code in zoekgebied_gevaren:
                    self.voeg_uniek_toe(
                        gevonden_gevaren_pics,
                        bestandsnaam
                    )
    
            pictogrammen_string = ",".join(
                gevonden_gevaren_pics
            )
    
            # -----------------------------------
            # PBM'S UIT RUBRIEK 8
            # -----------------------------------
    
            gevonden_pbm = []
            gevonden_pbm_pics = []
    
            # Gebruik bij voorkeur uitsluitend
            # rubriek 8 om foutieve detecties uit
            # andere rubrieken te voorkomen.
            zoekgebied_pbm = rubriek_8
    
            if not zoekgebied_pbm:
                print(
                    "[MSDS ANALYSE\]: "
                    "RUBRIEK 8 NIET GEVONDEN"
                )
    
            else:
                pbm_regels = [
                    (
                        [
                            "veiligheidsbril",
                            "oogbescherming",
                            "ruimzichtbril",
                            "gelaatsscherm",
                            "face shield",
                            "safety glasses",
                            "goggles",
                            "en 166",
                            "en166",
                        ],
                        "oog- en gelaatsbescherming",
                        "bril.png"
                    ),
                    (
                        [
                            "handschoen",
                            "handschoenen",
                            "nitril",
                            "butylrubber",
                            "neopreen",
                            "chemical resistant gloves",
                            "protective gloves",
                            "en 374",
                            "en374",
                        ],
                        "chemiebestendige handschoenen",
                        "handschoenen.png"
                    ),
                    (
                        [
                            "ademhaling",
                            "ademhalingsbescherming",
                            "ademhalingstoestel",
                            "respirator",
                            "breathing apparatus",
                            "filtermasker",
                            "ffp2",
                            "ffp3",
                            "en 143",
                            "en 149",
                        ],
                        "geschikte ademhalingsbescherming",
                        "masker.png"
                    ),
                    (
                        [
                            "beschermende kleding",
                            "chemical protective clothing",
                            "chemical suit",
                            "beschermend pak",
                            "chemicaliënpak",
                            "chemiepak",
                            "schort",
                            "apron",
                            "overall",
                            "en 13034",
                            "en13034",
                        ],
                        "chemisch beschermende kleding",
                        "schort.png"
                    ),
                    (
                        [
                            "veiligheidsschoenen",
                            "veiligheidslaarzen",
                            "beschermend schoeisel",
                            "protective footwear",
                            "safety shoes",
                            "safety boots",
                            "en 20345",
                            "en20345",
                            "en 13832",
                        ],
                        "geschikt veiligheidsschoeisel",
                        "schoenen.png"
                    ),
                    (
                        [
                            "gehoorbescherming",
                            "oordoppen",
                            "oorkappen",
                            "hearing protection",
                            "earmuffs",
                            "en 352",
                            "en352",
                        ],
                        "gehoorbescherming",
                        "gehoor.png"
                    ),
                    (
                        [
                            "veiligheidshelm",
                            "hoofdbescherming",
                            "head protection",
                            "safety helmet",
                            "en 397",
                            "en397",
                        ],
                        "een veiligheidshelm",
                        "helm.png"
                    ),
                ]
    
                for (
                    zoektermen,
                    omschrijving,
                    pictogram
                ) in pbm_regels:
                    if any(
                        term in zoekgebied_pbm
                        for term in zoektermen
                    ):
                        self.voeg_uniek_toe(
                            gevonden_pbm,
                            omschrijving
                        )
    
                        self.voeg_uniek_toe(
                            gevonden_pbm_pics,
                            pictogram
                        )
    
            if gevonden_pbm:
                pbm_tekst = (
                    "Draag in ieder geval "
                    + ", ".join(gevonden_pbm)
                    + "."
                )
            else:
                pbm_tekst = (
                    "De vereiste persoonlijke "
                    "beschermingsmiddelen konden niet "
                    "betrouwbaar uit rubriek 8 worden "
                    "herkend. Controleer de geldende "
                    "PBM matrix, werkvergunning en "
                    "werkinstructie."
                )
    
            pbm_pics_string = ",".join(
                gevonden_pbm_pics
            )
    
            # -----------------------------------
            # OOGSPOELINFORMATIE UIT RUBRIEK 4
            # -----------------------------------
    
            oog_tekst = (
                "Bij contact met de ogen direct "
                "spoelen met overvloedig water en "
                "de geldende noodprocedure volgen."
            )
    
            if rubriek_4:
                regels = [
                    regel.strip()
                    for regel in rubriek_4.splitlines()
                    if regel.strip()
                ]
    
                oog_regels = []
    
                oog_zoektermen = [
                    "oog",
                    "ogen",
                    "eye contact",
                    "eyes",
                    "spoelen",
                    "rinse",
                    "flush",
                ]
    
                for index, regel in enumerate(regels):
                    if any(
                        zoekterm in regel
                        for zoekterm in oog_zoektermen
                    ):
                        self.voeg_uniek_toe(
                            oog_regels,
                            regel
                        )
    
                        # Soms staat de instructie op
                        # de opvolgende regel.
                        if index + 1 < len(regels):
                            volgende_regel = (
                                regels[index + 1]
                            )
    
                            if len(volgende_regel) > 15:
                                self.voeg_uniek_toe(
                                    oog_regels,
                                    volgende_regel
                                )
    
                if oog_regels:
                    oog_tekst = " ".join(
                        oog_regels[:3]
                    ).strip()
    
            # -----------------------------------
            # GEVARENTEXT UIT RUBRIEK 2
            # -----------------------------------
    
            gevaren_tekst = (
                "Zie het veiligheidsblad voor "
                "de specifieke gevaren."
            )
    
            if rubriek_2:
                gevaar_regels = []
    
                for regel in rubriek_2.splitlines():
                    regel = regel.strip()
    
                    if len(regel) < 15:
                        continue
    
                    if (
                        re.search(
                            r"\bh[234]\d{2}\b",
                            regel
                        )
                        or "veroorzaakt" in regel
                        or "gevaar" in regel
                        or "fatal" in regel
                        or "toxic" in regel
                        or "causes" in regel
                    ):
                        self.voeg_uniek_toe(
                            gevaar_regels,
                            regel
                        )
    
                if gevaar_regels:
                    gevaren_tekst = (
                        "Belangrijkste gevaren: "
                        + " ".join(
                            gevaar_regels[:4]
                        )
                    )
    
            resultaat = {
                "naam": stofnaam,
    
                # Een SDS bevat gewoonlijk niet
                # afzonderlijk een PBM-set voor jullie
                # lab en fabriek. Daarom krijgen beide
                # voorlopig dezelfde SDS-informatie.
                "pbm_lab": pbm_tekst,
                "pbm_fabriek": pbm_tekst,
    
                "pbm_pic_lab": pbm_pics_string,
                "pbm_pic_fabriek": pbm_pics_string,
    
                "pictogram": pictogrammen_string,
                "n_ogen": oog_tekst,
                "msds": Path(pdf_pad).name,
                "gevaren": gevaren_tekst,
                "pdf_geanalyseerd": True,
            }
    
            print(
                "[MSDS ANALYSE\]: KLAAR "
                f"{stofnaam}"
            )
    
            print(
                "[MSDS PBM\]: "
                f"{pbm_tekst}"
            )
    
            print(
                "[MSDS PBM PICTOGRAMMEN\]: "
                f"{pbm_pics_string or 'GEEN'}"
            )
    
            print(
                "[MSDS GHS PICTOGRAMMEN\]: "
                f"{pictogrammen_string or 'GEEN'}"
            )
    
            return resultaat
    
        except Exception as fout:
            print(
                "[MSDS ANALYSE FOUT\]: "
                f"{type(fout).__name__}: {fout} "
                f"BIJ {pdf_pad}"
            )
    
            return None

    def laad_stoffen(self):
        """
        Bouwt de database volledig op uit de PDF-bestanden
        in de map msds. Er wordt geen CSV gebruikt.
        """
    
        database = {}
    
        if not os.path.exists(MSDS_DIR):
            print(
                "[DATABASE FOUT\]: "
                f"MSDS-map bestaat niet: {MSDS_DIR}"
            )
    
            return database
    
        pdf_bestanden = sorted(
            bestand
            for bestand in os.listdir(MSDS_DIR)
            if bestand.lower().endswith(".pdf")
        )
    
        totaal = len(pdf_bestanden)
    
        print(
            f"[MSDS ANALYSE]: {totaal} "
            "PDF-BESTANDEN ANALYSEREN"
        )
    
        for nummer, bestand in enumerate(
            pdf_bestanden,
            1
        ):
            pdf_pad = os.path.join(
                MSDS_DIR,
                bestand
            )
    
            print(
                f"[MSDS ANALYSE]: "
                f"{nummer}/{totaal} {bestand}"
            )
    
            pdf_data = self.analyseer_msds_pdf(
                pdf_pad
            )
    
            if not pdf_data:
                print(
                    "[MSDS ANALYSE]: "
                    f"OVERSLAAN {bestand}"
                )
    
                continue
    
            stof_id = self.normaliseer_stofnaam(
                pdf_data["naam"]
            )
    
            if not stof_id:
                continue
    
            database[stof_id] = pdf_data
    
            print(
                "[PDF STOF GEREGISTREERD]: "
                f"{stof_id} -> {bestand}"
            )
    
        print(
            f"{len(database)} stoffen "
            "volledig geanalyseerd uit PDF-bestanden"
        )
    
        return database

    def vind_beste_stof(self, opdracht):
        if not opdracht or not self.lab_database: return None
        woorden = re.findall(r"[a-zA-Z0-9À-ÿ]+", opdracht.lower())
        ids = list(self.lab_database)
        combinatie = self.normaliseer_stofnaam(" ".join(woorden))
        for sid in ids:
            if sid and (sid in combinatie or combinatie in sid): return sid
        for woord in woorden:
            matches = difflib.get_close_matches(self.normaliseer_stofnaam(woord), ids, n=1, cutoff=0.6)
            if matches: return matches[0]
        return None

    def lees_gevaren_voor(self, info):
        self.update_ui(f"GEVAREN: {info.get('naam', '')}", "#FF4500", "#FFFFFF", info.get("pictogram", ""))
        time.sleep(4)
        self.update_ui("CHEMI", BG_STANDBY, KLEUR_TEKST_DONKER)

    def open_msds(self, info):
        pdf = info.get("msds", "")
        pdf_pad = os.path.join(MSDS_DIR, pdf)
        if not pdf or not os.path.exists(pdf_pad):
            print(f"[PDF FOUT]: BESTAND NIET GEVONDEN: {pdf_pad}")
            return

        self.update_ui(
            "PDF LADEN...",
            BG_STANDBY,
            KLEUR_TEKST_DONKER
        )

        def laden():
            paginas = self.pdf_renderer.pagina_paden(pdf_pad)
            if not paginas:
                paginas = self.pdf_renderer.render(pdf_pad)
            if paginas:
                Clock.schedule_once(
                    lambda dt: self.toon_pdf_in_app(pdf_pad, paginas)
                )
            else:
                Clock.schedule_once(
                    lambda dt: self.update_ui(
                        "PDF KON NIET WORDEN GERENDERD", KLEUR_NOOD, "#FFFFFF"
                    )
                )

        threading.Thread(target=laden, daemon=True).start()

    def schoonmaak_bij_opstart(self):
        try:
            for naam in os.listdir(self.TEMP_PDF_DIR):
                pad = os.path.join(self.TEMP_PDF_DIR, naam)
                if os.path.isfile(pad): os.remove(pad)
        except Exception as fout:
            print(f"Opschoonfout: {fout}")


if __name__ == "__main__":
    ChemieApp().run()
