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

# ---------------------------------------------------------
# KIVY-INSTELLINGEN
# Deze instellingen moeten vóór de overige Kivy-imports staan.
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# DESKTOPMODULES
#
# Deze modules worden NIET op Android geïmporteerd.
# Hierdoor voorkomen we de eerdere crashes met edge_tts
# en pygame.
# ---------------------------------------------------------

if platform != "android":
    try:
        import edge_tts
    except ImportError:
        edge_tts = None

    try:
        import pygame
    except ImportError:
        pygame = None

    try:
        import speech_recognition as sr
    except ImportError:
        sr = None
else:
    edge_tts = None
    pygame = None
    sr = None


# ---------------------------------------------------------
# ANDROIDMODULES
# ---------------------------------------------------------

if platform == "android":
    try:
        from android.permissions import request_permissions, Permission
    except ImportError:
        request_permissions = None
        Permission = None


# ---------------------------------------------------------
# MAPPEN EN BESTANDSPADEN
# ---------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ASSETS_DIR = os.path.join(BASE_DIR, "assets")
PICTO_DIR = os.path.join(BASE_DIR, "pictogrammen")
MSDS_DIR = os.path.join(BASE_DIR, "msds")

STOFFEN_CSV = os.path.join(BASE_DIR, "stoffen.csv")


# ---------------------------------------------------------
# KLEUREN EN INSTELLINGEN
# ---------------------------------------------------------

BG_STANDBY = "#F5EFDB"
KLEUR_TEKST_DONKER = "#273F53"
KLEUR_LUISTEREN = "#2ECC71"
KLEUR_VRAAG = "#F1C40F"
KLEUR_NOOD = "#E74C3C"
KLEUR_KEUZE = "#3498DB"
KLEUR_MUTE = "#FFFFFF"
KLEUR_STOP = "#E74C3C"
KLEUR_TEKST_WIT = "#E74C3C"

INTRO_DUUR = 2.5

Window.clearcolor = get_color_from_hex(BG_STANDBY)


# ---------------------------------------------------------
# LETTERTYPE
# ---------------------------------------------------------

FONT_PAD = os.path.join(ASSETS_DIR, "Monas-BLBW8.ttf")

try:
    if os.path.exists(FONT_PAD):
        LabelBase.register(
            name="MijnFont",
            fn_regular=FONT_PAD
        )
        GEBRUIK_FONT = "MijnFont"
    else:
        GEBRUIK_FONT = "Roboto"
except Exception as fout:
    print(f"Lettertype kon niet worden geladen: {fout}")
    GEBRUIK_FONT = "Roboto"


# ---------------------------------------------------------
# VOORTGANGSBALK
# ---------------------------------------------------------

class ProgressWidget(Widget):
    value = NumericProperty(900)
    max = NumericProperty(900)


# ---------------------------------------------------------
# HOOFDAPPLICATIE
# ---------------------------------------------------------

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

        # Schrijfbare Android-map.
        self.DATA_DIR = self.user_data_dir
        self.TEMP_PDF_DIR = os.path.join(self.DATA_DIR, "temp_pdf")
        self.NOODLOG_PAD = os.path.join(self.DATA_DIR, "noodlog.csv")

        self.maak_schrijfbare_mappen()

        # Geluidsbestanden laden met Kivy SoundLoader.
        # Dit werkt beter op Android dan pygame.
        self.alarm_sound = self.laad_geluid("alarm.wav")
        self.ping_sound = self.laad_geluid("ping.wav")
        self.intro_audio = self.laad_geluid("intro_audio.mp3")

        # -------------------------------------------------
        # HOOFDLAYOUT
        # -------------------------------------------------

        self.root_layout = FloatLayout()

        with self.root_layout.canvas.before:
            self.bg_color = Color(
                rgba=get_color_from_hex(BG_STANDBY)
            )

            self.bg_rect = Rectangle(
                size=Window.size,
                pos=(0, 0)
            )

        self.root_layout.bind(
            size=self._update_rect,
            pos=self._update_rect
        )

        # -------------------------------------------------
        # CENTRALE INTERFACE
        # -------------------------------------------------

        self.ui = BoxLayout(
            orientation="vertical",
            padding=50,
            spacing=20,
            size_hint=(1, 1)
        )

        self.pic_layout = BoxLayout(
            orientation="horizontal",
            size_hint=(1, 0.001),
            spacing=20
        )

        self.centraal_label = Label(
            text="CHEMI",
            font_name=GEBRUIK_FONT,
            font_size="100sp",
            opacity=0,
            bold=True,
            halign="center",
            valign="middle",
            color=get_color_from_hex(KLEUR_TEKST_DONKER)
        )

        self.centraal_label.bind(
            size=self._update_label_text_size
        )

        self.status_log = Label(
            text=" ",
            font_size="14sp",
            size_hint=(1, 0.1),
            color=get_color_from_hex("#7F8C8D"),
            halign="center",
            valign="middle"
        )

        self.status_log.bind(
            size=self._update_label_text_size
        )

        # -------------------------------------------------
        # VOORTGANGSBALK
        # -------------------------------------------------

        self.progress = ProgressWidget(
            size_hint=(0.6, 0.01),
            pos_hint={
                "center_x": 0.5,
                "y": 0.15
            },
            opacity=0
        )

        with self.progress.canvas:
            self.bg_bar_color = Color(
                rgba=get_color_from_hex("#BDC3C7")
            )

            self.bar_bg_rect = Rectangle(
                pos=self.progress.pos,
                size=self.progress.size
            )

            self.fill_bar_color = Color(
                rgba=get_color_from_hex("#FFFFFF")
            )

            self.bar_fill_rect = Rectangle(
                pos=self.progress.pos,
                size=self.progress.size
            )

        self.progress.bind(
            pos=self.update_progress_rects,
            size=self.update_progress_rects,
            value=self.update_progress_rects,
            max=self.update_progress_rects
        )

        self.ui.add_widget(self.pic_layout)
        self.ui.add_widget(self.centraal_label)
        self.ui.add_widget(self.status_log)

        self.root_layout.add_widget(self.ui)
        self.root_layout.add_widget(self.progress)

        # -------------------------------------------------
        # LOCATIEKNOPPEN
        # -------------------------------------------------

        self.btn_layout_locatie = BoxLayout(
            orientation="horizontal",
            size_hint=(None, None),
            size=(500, 75),
            pos_hint={
                "center_x": 0.5,
                "y": -0.3
            },
            spacing=40,
            opacity=0
        )

        btn_style = {
            "background_normal": "",
            "font_size": "22sp",
            "bold": True
        }

        self.btn_lab = Button(
            text="LABORATORIUM",
            background_color=get_color_from_hex(
                KLEUR_TEKST_DONKER
            ),
            **btn_style
        )

        self.btn_fabriek = Button(
            text="FABRIEK",
            background_color=get_color_from_hex(
                KLEUR_TEKST_DONKER
            ),
            **btn_style
        )

        self.btn_lab.bind(
            on_release=lambda knop: self.set_locatie("lab")
        )

        self.btn_fabriek.bind(
            on_release=lambda knop: self.set_locatie("fabriek")
        )

        self.btn_layout_locatie.add_widget(self.btn_lab)
        self.btn_layout_locatie.add_widget(self.btn_fabriek)

        self.root_layout.add_widget(self.btn_layout_locatie)

        # -------------------------------------------------
        # NOODSTOPKNOP
        # -------------------------------------------------

        self.btn_nood_stop = Button(
            text="STOP NOODPROCEDURE",
            size_hint=(None, None),
            size=(400, 100),
            pos_hint={
                "center_x": 0.7,
                "y": -0.2
            },
            background_normal="",
            background_color=(1, 1, 1, 1),
            color=get_color_from_hex(KLEUR_NOOD),
            bold=True,
            font_size="24sp",
            opacity=0
        )

        self.btn_nood_stop.bind(
            on_release=self.stop_noodprocedure
        )

        self.root_layout.add_widget(self.btn_nood_stop)

        # -------------------------------------------------
        # ALARM DEMPEN
        # -------------------------------------------------

        self.btn_alarm_mute = Button(
            text="ALARM\nDEMPEN",
            size_hint=(None, None),
            size=(220, 100),
            pos_hint={
                "center_x": 0.3,
                "y": -0.2
            },
            background_normal="",
            background_color=get_color_from_hex(KLEUR_MUTE),
            color=get_color_from_hex(KLEUR_TEKST_WIT),
            bold=True,
            halign="center",
            font_size="20sp",
            opacity=0
        )

        self.btn_alarm_mute.bind(
            on_release=self.mute_alarm
        )

        self.root_layout.add_widget(self.btn_alarm_mute)

        # -------------------------------------------------
        # PDF-WEERGAVE
        # -------------------------------------------------

        self.pdf_scroll_view = ScrollView(
            size_hint=(0.9, 0.80),
            pos_hint={
                "center_x": 0.5,
                "center_y": 0.58
            },
            do_scroll_x=False,
            do_scroll_y=True,
            opacity=0
        )

        self.pdf_scroll_view.bind(
            on_scroll_start=self.handmatige_scroll_detectie
        )

        self.pdf_controls = BoxLayout(
            orientation="horizontal",
            size_hint=(None, None),
            size=(550, 110),
            pos_hint={
                "center_x": 0.52,
                "y": -0.2
            },
            padding=10,
            spacing=20
        )

        self.btn_prev = Button(
            background_normal=self.asset_pad("vorige_knop.png"),
            size_hint=(None, None),
            size=(100, 100)
        )

        self.btn_pauze = Button(
            background_normal=self.asset_pad("pauze_knop.png"),
            size_hint=(None, None),
            size=(100, 100)
        )

        self.btn_next = Button(
            background_normal=self.asset_pad("volgende_knop.png"),
            size_hint=(None, None),
            size=(100, 100)
        )

        self.btn_stop = Button(
            background_normal=self.asset_pad("stop_knop.png"),
            size_hint=(None, None),
            size=(100, 100)
        )

        self.btn_prev.bind(
            on_release=lambda knop: self.wissel_pagina(-1)
        )

        self.btn_pauze.bind(
            on_release=self.toggle_pauze
        )

        self.btn_next.bind(
            on_release=lambda knop: self.wissel_pagina(1)
        )

        self.btn_stop.bind(
            on_release=self.sluit_pdf
        )

        for widget in [
            self.btn_prev,
            self.btn_pauze,
            self.btn_next,
            self.btn_stop
        ]:
            self.pdf_controls.add_widget(widget)

        self.root_layout.add_widget(self.pdf_scroll_view)
        self.root_layout.add_widget(self.pdf_controls)

        Clock.schedule_once(
            self.start_intro_sequentie,
            0.5
        )

        return self.root_layout

    # -----------------------------------------------------
    # OPSTARTEN EN PERMISSIES
    # -----------------------------------------------------

    def on_start(self):
        if platform == "android":
            self.vraag_android_permissies()

    def vraag_android_permissies(self):
        if request_permissions is None or Permission is None:
            print("Android-permissiemodule is niet beschikbaar.")
            return

        try:
            permissies = [
                Permission.RECORD_AUDIO
            ]

            if hasattr(Permission, "READ_EXTERNAL_STORAGE"):
                permissies.append(
                    Permission.READ_EXTERNAL_STORAGE
                )

            if hasattr(Permission, "WRITE_EXTERNAL_STORAGE"):
                permissies.append(
                    Permission.WRITE_EXTERNAL_STORAGE
                )

            request_permissions(permissies)

        except Exception as fout:
            print(
                f"Android-permissies konden niet worden "
                f"aangevraagd: {fout}"
            )

    # -----------------------------------------------------
    # HULPFUNCTIES BESTANDEN EN AUDIO
    # -----------------------------------------------------

    def maak_schrijfbare_mappen(self):
        try:
            os.makedirs(
                self.TEMP_PDF_DIR,
                exist_ok=True
            )
        except Exception as fout:
            print(
                f"Tijdelijke map kon niet worden gemaakt: {fout}"
            )

    def asset_pad(self, bestandsnaam):
        return os.path.join(
            ASSETS_DIR,
            bestandsnaam
        )

    def pictogram_pad(self, bestandsnaam):
        return os.path.join(
            PICTO_DIR,
            bestandsnaam
        )

    def laad_geluid(self, bestandsnaam):
        geluid_pad = self.asset_pad(bestandsnaam)

        if not os.path.exists(geluid_pad):
            print(
                f"Geluidsbestand niet gevonden: {geluid_pad}"
            )
            return None

        try:
            geluid = SoundLoader.load(geluid_pad)

            if geluid is None:
                print(
                    f"SoundLoader kon bestand niet laden: "
                    f"{geluid_pad}"
                )

            return geluid

        except Exception as fout:
            print(
                f"Geluidsbestand kon niet worden geladen: {fout}"
            )
            return None

    def speel_geluid(self, geluid, herhalen=False):
        if geluid is None:
            return

        try:
            geluid.loop = herhalen
            geluid.stop()
            geluid.play()
        except Exception as fout:
            print(f"Geluid kon niet worden afgespeeld: {fout}")

    def stop_geluid(self, geluid):
        if geluid is None:
            return

        try:
            geluid.stop()
        except Exception as fout:
            print(f"Geluid kon niet worden gestopt: {fout}")

    # -----------------------------------------------------
    # UI-HULPFUNCTIES
    # -----------------------------------------------------

    def _update_rect(self, instance, value):
        self.bg_rect.pos = instance.pos
        self.bg_rect.size = instance.size

    def _update_label_text_size(self, instance, size):
        instance.text_size = size

    def update_progress_rects(self, obj, *args):
        self.bar_bg_rect.pos = obj.pos
        self.bar_bg_rect.size = obj.size

        if obj.max > 0:
            vul_breedte = (obj.value / obj.max) * obj.width
        else:
            vul_breedte = 0

        vul_breedte = max(
            0,
            min(vul_breedte, obj.width)
        )

        self.bar_fill_rect.pos = obj.pos
        self.bar_fill_rect.size = (
            vul_breedte,
            obj.height
        )

    def log_status(self, bericht):
        print(f"STATUS: {bericht}")

        if hasattr(self, "status_log"):
            Clock.schedule_once(
                lambda dt, tekst=str(bericht):
                    setattr(self.status_log, "text", tekst)
            )

    def update_ui(
        self,
        tekst,
        hex_bg,
        hex_txt,
        pic_string=None
    ):
        def change(dt):
            self.centraal_label.text = str(tekst).upper()

            Animation(
                rgba=get_color_from_hex(hex_bg),
                duration=0.6
            ).start(self.bg_color)

            Animation(
                color=get_color_from_hex(hex_txt),
                duration=0.6
            ).start(self.centraal_label)

            self.pic_layout.clear_widgets()

            if pic_string:
                pictogrammen = [
                    item.strip()
                    for item in pic_string.split(",")
                    if item.strip()
                ]

                for bestandsnaam in pictogrammen:
                    pad = self.pictogram_pad(bestandsnaam)

                    if os.path.exists(pad):
                        afbeelding = Image(
                            source=pad,
                            allow_stretch=True
                        )

                        self.pic_layout.add_widget(afbeelding)

                self.pic_layout.size_hint_y = 0.6
                self.centraal_label.size_hint_y = 0.4

            else:
                self.pic_layout.size_hint_y = 0.001
                self.centraal_label.size_hint_y = 1.0

        Clock.schedule_once(change)

    # -----------------------------------------------------
    # INTRODUCTIE
    # -----------------------------------------------------

    def start_intro_sequentie(self, dt):
        self.speel_geluid(self.intro_audio)

        animatie = Animation(
            opacity=1,
            duration=INTRO_DUUR,
            t="out_quad"
        )

        animatie.bind(
            on_complete=self.activeer_spraak_systeem
        )

        animatie.start(self.centraal_label)

    def activeer_spraak_systeem(self, *args):
        threading.Thread(
            target=self.initialiseer_audio_en_loop,
            daemon=True
        ).start()

    # -----------------------------------------------------
    # SPRAAK EN TTS
    # -----------------------------------------------------

    def assistent_spreekt(self, tekst):
        if platform == "android":
            print(f"[Android TTS nog uitgeschakeld]: {tekst}")
            return

        if edge_tts is None:
            print(f"[Edge TTS niet beschikbaar]: {tekst}")
            return

        bestandsnaam = os.path.join(
            self.DATA_DIR,
            f"spraak_{int(time.time() * 1000)}.mp3"
        )

        try:
            asyncio.run(
                edge_tts.Communicate(
                    tekst,
                    "nl-NL-FennaNeural"
                ).save(bestandsnaam)
            )

            tijdelijk_geluid = SoundLoader.load(bestandsnaam)

            if tijdelijk_geluid is not None:
                tijdelijk_geluid.play()

                while tijdelijk_geluid.state == "play":
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

            threading.Thread(
                target=self.automatische_map_scanner,
                daemon=True
            ).start()

            if platform == "android":
                self.log_status(
                    "ANDROID TESTMODUS - SPRAAKHERKENNING NOG UIT"
                )
            else:
                self.log_status(
                    "SYSTEEM GEREED - LUISTEREND..."
                )

            self.hoofd_loop()

        except Exception as fout:
            print(
                f"Opstartfout in audiosysteem: {fout}"
            )

    def hoofd_loop(self):
        if platform == "android":
            while True:
                time.sleep(2)

            return

        if sr is None:
            self.log_status(
                "SPRAAKHERKENNING NIET BESCHIKBAAR"
            )
            return

        try:
            self.recognizer = sr.Recognizer()
            self.recognizer.energy_threshold = 300
            self.recognizer.dynamic_energy_threshold = False
            self.recognizer.pause_threshold = 0.5

        except Exception as fout:
            self.log_status(
                f"SPRAAKHERKENNING KON NIET STARTEN: {fout}"
            )
            return

        while True:
            if self.nood_actief:
                time.sleep(1)
                continue

            try:
                with sr.Microphone() as source:
                    audio = self.recognizer.listen(
                        source,
                        timeout=None,
                        phrase_time_limit=3
                    )

                input_t = self.recognizer.recognize_google(
                    audio,
                    language="nl-NL"
                ).lower()

                if not input_t:
                    continue

                print(f"{input_t}")

                noodwoorden = [
                    "oog",
                    "ogen",
                    "nood",
                    "help",
                    "spoelen"
                ]

                if (
                    any(
                        woord in input_t
                        for woord in noodwoorden
                    )
                    and "chemie" not in input_t
                ):
                    stof_id = self.vind_beste_stof(input_t)

                    if stof_id:
                        info = self.lab_database[stof_id]

                        Clock.schedule_once(
                            lambda dt, gegevens=info:
                                self.start_nood_timer(gegevens)
                        )

                        continue

                if "chemie" in input_t:
                    self.speel_geluid(self.ping_sound)

                    self.update_ui(
                        "LUISTEREN",
                        "#F0D876",
                        "#273F53"
                    )

                    self.assistent_spreekt(
                        "Wat kan ik voor u doen?"
                    )

                    self.speel_geluid(self.ping_sound)

                    self.verwerk_vervolgvraag()

            except sr.UnknownValueError:
                pass

            except Exception as fout:
                print(f"Spraakloopfout: {fout}")
                time.sleep(1)

            if (
                not self.nood_actief
                and not self.systeem_bezet
                and self.centraal_label.text != "CHEMI"
            ):
                self.update_ui(
                    "CHEMI",
                    BG_STANDBY,
                    KLEUR_TEKST_DONKER
                )

    def verwerk_vervolgvraag(self):
        if sr is None or self.recognizer is None:
            return

        try:
            with sr.Microphone() as source:
                audio = self.recognizer.listen(
                    source,
                    timeout=5,
                    phrase_time_limit=5
                )

            vraag = self.recognizer.recognize_google(
                audio,
                language="nl-NL"
            ).lower()

            print(f"{vraag}")

            stof_id = self.vind_beste_stof(vraag)

            if not stof_id:
                self.assistent_spreekt(
                    "Stof niet herkend."
                )
                return

            info = self.lab_database[stof_id]

            if any(
                woord in vraag
                for woord in [
                    "gevaar",
                    "risico",
                    "gevaarlijk"
                ]
            ):
                self.lees_gevaren_voor(info)

            elif any(
                woord in vraag
                for woord in [
                    "pdf",
                    "msds",
                    "blad"
                ]
            ):
                self.open_msds(info)

            else:
                self.systeem_bezet = True

                threading.Thread(
                    target=self.vraag_locatie_en_antwoord,
                    args=(info,),
                    daemon=True
                ).start()

        except sr.UnknownValueError:
            print("Geen vraag begrepen na activatie.")

        except sr.WaitTimeoutError:
            print("Wachttijd voor vraag verlopen.")

        except Exception as fout:
            print(f"Fout bij vervolgvraag: {fout}")

    # -----------------------------------------------------
    # LOCATIE SELECTEREN
    # -----------------------------------------------------

    def set_locatie(self, locatie):
        print(f"Locatie gekozen: {locatie}")

        self.gekozen_locatie = locatie
        self.keuze_event.set()

    def vraag_locatie_en_antwoord(self, info):
        self.systeem_bezet = True
        self.gekozen_locatie = None
        self.keuze_event.clear()

        try:
            self.update_ui(
                "KIES LOCATIE",
                KLEUR_KEUZE,
                "#FFFFFF",
                info.get("pictogram", "")
            )

            Clock.schedule_once(
                lambda dt:
                    Animation(
                        pos_hint={
                            "center_x": 0.5,
                            "y": 0.1
                        },
                        opacity=1,
                        duration=0.5
                    ).start(self.btn_layout_locatie)
            )

            self.assistent_spreekt(
                "Is dit voor het laboratorium of de fabriek?"
            )

            self.speel_geluid(self.ping_sound)

            # Spraakselectie alleen op desktop.
            if (
                platform != "android"
                and sr is not None
                and self.recognizer is not None
            ):
                try:
                    with sr.Microphone() as source:
                        audio = self.recognizer.listen(
                            source,
                            timeout=5,
                            phrase_time_limit=3
                        )

                    keuze = self.recognizer.recognize_google(
                        audio,
                        language="nl-NL"
                    ).lower()

                    if (
                        "lab" in keuze
                        or "laboratorium" in keuze
                    ):
                        self.set_locatie("lab")

                    elif (
                        "fabriek" in keuze
                        or "hal" in keuze
                    ):
                        self.set_locatie("fabriek")

                except Exception as fout:
                    print(
                        f"Locatie niet via spraak gekozen: {fout}"
                    )

            start_wachten = time.time()

            while (
                not self.keuze_event.is_set()
                and time.time() - start_wachten < 15
            ):
                time.sleep(0.1)

            Clock.schedule_once(
                lambda dt:
                    Animation(
                        pos_hint={
                            "center_x": 0.5,
                            "y": -0.3
                        },
                        opacity=0,
                        duration=0.3
                    ).start(self.btn_layout_locatie)
            )

            locatie = (
                self.gekozen_locatie
                if self.gekozen_locatie
                else "lab"
            )

            if locatie == "lab":
                pbm_tekst = info.get("pbm_lab", "")
                pbm_pics = info.get(
                    "pbm_pic_lab",
                    ""
                )
            else:
                pbm_tekst = info.get(
                    "pbm_fabriek",
                    ""
                )

                pbm_pics = info.get(
                    "pbm_pic_fabriek",
                    ""
                )

            self.update_ui(
                info.get("naam", "ONBEKENDE STOF"),
                KLEUR_LUISTEREN,
                "#FFFFFF",
                pbm_pics
            )

            self.assistent_spreekt(
                f"De PBM's voor het {locatie} zijn: "
                f"{pbm_tekst}"
            )

            time.sleep(3)

        except Exception as fout:
            print(f"Fout bij locatiekeuze: {fout}")

        finally:
            self.systeem_bezet = False

            self.update_ui(
                "CHEMI",
                BG_STANDBY,
                KLEUR_TEKST_DONKER
            )

    # -----------------------------------------------------
    # NOODPROCEDURE
    # -----------------------------------------------------

    def start_nood_timer(self, info, minuten=15):
        self.nood_actief = True
        self.systeem_bezet = True
        self.timer_seconds = minuten * 60

        self.update_ui(
            f"NOODGEVAL\n{minuten}:00",
            KLEUR_NOOD,
            "#FFFFFF",
            info.get("pictogram", "")
        )

        self.progress.max = self.timer_seconds
        self.progress.value = self.timer_seconds
        self.progress.opacity = 1

        self.speel_geluid(
            self.alarm_sound,
            herhalen=True
        )

        if self.timer_event:
            self.timer_event.cancel()

        self.timer_event = Clock.schedule_interval(
            lambda dt: self._timer_tick(info),
            1
        )

        Animation(
            pos_hint={
                "center_x": 0.3,
                "y": 0.05
            },
            opacity=1,
            duration=0.5
        ).start(self.btn_alarm_mute)

        Animation(
            pos_hint={
                "center_x": 0.7,
                "y": 0.05
            },
            opacity=1,
            duration=0.5
        ).start(self.btn_nood_stop)

        self.btn_alarm_mute.disabled = False
        self.btn_alarm_mute.text = "ALARM UIT"

        tekst = info.get(
            "n_ogen",
            f"Begin direct met spoelen voor {minuten} minuten."
        )

        threading.Thread(
            target=self.assistent_spreekt,
            args=(tekst,),
            daemon=True
        ).start()

    def _timer_tick(self, info):
        if not self.nood_actief:
            return False

        self.timer_seconds -= 1
        self.progress.value = self.timer_seconds

        minuten, seconden = divmod(
            self.timer_seconds,
            60
        )

        self.centraal_label.text = (
            f"NOODGEVAL\n"
            f"{minuten:02d}:{seconden:02d}"
        )

        if self.timer_seconds <= 0:
            self.stop_timer_voltooid()
            return False

        return True

    def stop_timer_voltooid(self):
        self.stop_geluid(self.alarm_sound)

        self.update_ui(
            "KLAAR",
            "#27AE60",
            "#FFFFFF"
        )

        threading.Thread(
            target=self.assistent_spreekt,
            args=(
                "De spoeltijd is voorbij. "
                "Controleer het oog.",
            ),
            daemon=True
        ).start()

    def stop_noodprocedure(self, *args):
        self.nood_actief = False
        self.systeem_bezet = False

        if self.timer_event:
            self.timer_event.cancel()
            self.timer_event = None

        self.stop_geluid(self.alarm_sound)

        self.progress.opacity = 0

        Animation(
            pos_hint={
                "center_x": 0.3,
                "y": -0.2
            },
            opacity=0,
            duration=0.5
        ).start(self.btn_alarm_mute)

        Animation(
            pos_hint={
                "center_x": 0.7,
                "y": -0.2
            },
            opacity=0,
            duration=0.5
        ).start(self.btn_nood_stop)

        self.update_ui(
            "CHEMI",
            BG_STANDBY,
            KLEUR_TEKST_DONKER
        )

        self.log_status(
            "NOODPROCEDURE GESTOPT"
        )

    def mute_alarm(self, instance):
        self.stop_geluid(self.alarm_sound)

        instance.text = "ALARM UITGEZET"
        instance.disabled = True

        self.log_status(
            "ALARM HANDMATIG UITGEZET"
        )

    def log_noodgeval(self, stof):
        try:
            nieuw_bestand = not os.path.exists(
                self.NOODLOG_PAD
            )

            with open(
                self.NOODLOG_PAD,
                "a",
                encoding="utf-8",
                newline=""
            ) as bestand:
                schrijver = csv.writer(bestand)

                if nieuw_bestand:
                    schrijver.writerow([
                        "datum_tijd",
                        "stof"
                    ])

                schrijver.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S"),
                    stof
                ])

        except Exception as fout:
            print(
                f"Noodgeval kon niet worden gelogd: {fout}"
            )

    def forceer_nood_ogen_zoutzuur(self, info):
        self.log_noodgeval(
            info.get("naam", "Onbekend")
        )

        self.start_nood_timer(
            info,
            minuten=15
        )

    # -----------------------------------------------------
    # PDF-WEERGAVE
    # -----------------------------------------------------

    def toon_pdf_in_app(self, pdf_pad):
        self.pdf_is_pauze = False
        self.systeem_bezet = True

        self.update_ui(
            "PDF WEERGAVE",
            BG_STANDBY,
            KLEUR_TEKST_DONKER
        )

        try:
            reader = PdfReader(pdf_pad)

            self.pdf_paginas_tekst = [
                pagina.extract_text()
                or "Geen tekst op deze pagina."
                for pagina in reader.pages
            ]

            self.totaal_pdf_paginas = len(
                self.pdf_paginas_tekst
            )

            if self.totaal_pdf_paginas == 0:
                self.pdf_paginas_tekst = [
                    "Deze PDF bevat geen leesbare pagina's."
                ]

                self.totaal_pdf_paginas = 1

        except Exception as fout:
            print(f"PDF kon niet worden geladen: {fout}")

            self.pdf_paginas_tekst = [
                "Kan PDF-tekst niet laden."
            ]

            self.totaal_pdf_paginas = 1

        if not hasattr(self, "pdf_text_label"):
            self.pdf_scroll_view.clear_widgets()

            self.pdf_text_label = Label(
                font_name=GEBRUIK_FONT,
                font_size="22sp",
                color=get_color_from_hex(
                    KLEUR_TEKST_DONKER
                ),
                size_hint_y=None,
                halign="left",
                valign="top",
                padding=(20, 20)
            )

            self.pdf_text_label.bind(
                width=self._update_pdf_text_width
            )

            self.pdf_text_label.bind(
                texture_size=self._update_pdf_text_height
            )

            self.pdf_scroll_view.add_widget(
                self.pdf_text_label
            )

        self.pdf_scroll_view.opacity = 1

        Animation(
            pos_hint={
                "center_x": 0.52,
                "y": 0.02
            },
            duration=0.5
        ).start(self.pdf_controls)

        self.scroll_pagina(
            0,
            self.totaal_pdf_paginas
        )

    def _update_pdf_text_width(self, instance, width):
        instance.text_size = (
            max(width - 40, 100),
            None
        )

    def _update_pdf_text_height(
        self,
        instance,
        texture_size
    ):
        instance.height = texture_size[1] + 40

    def handmatige_scroll_detectie(
        self,
        instance,
        touch
    ):
        if self.huidige_pdf_anim:
            self.huidige_pdf_anim.stop(
                self.pdf_scroll_view
            )

            self.huidige_pdf_anim = None

        self.pdf_is_pauze = True

        self.btn_pauze.background_normal = self.asset_pad(
            "verder_knop.png"
        )

        self.log_status(
            "HANDMATIG SCROLLEN - PAUZE"
        )

        return False

    def scroll_pagina(self, index, totaal):
        if index >= totaal:
            self.sluit_pdf()
            return

        if index < 0:
            return

        self.huidige_pdf_index = index

        self.pdf_text_label.text = (
            self.pdf_paginas_tekst[index]
        )

        self.pdf_scroll_view.scroll_y = 1.0

        if index == 0:
            self.ui.opacity = 0

        if not self.pdf_is_pauze:
            if self.huidige_pdf_anim:
                self.huidige_pdf_anim.stop(
                    self.pdf_scroll_view
                )

            self.huidige_pdf_anim = Animation(
                scroll_y=0,
                duration=self.scroll_snelheid_standaard,
                t="linear"
            )

            self.huidige_pdf_anim.bind(
                on_complete=self._pdf_anim_klaar
            )

            Clock.schedule_once(
                self._safe_start_anim,
                0.1
            )

    def _safe_start_anim(self, dt=None):
        if (
            not self.pdf_is_pauze
            and self.huidige_pdf_anim
        ):
            self.huidige_pdf_anim.start(
                self.pdf_scroll_view
            )

    def _pdf_anim_klaar(self, *args):
        if (
            not self.pdf_is_pauze
            and self.pdf_scroll_view.scroll_y <= 0.02
        ):
            self.wissel_pagina(1)

    def wissel_pagina(self, richting):
        nieuwe_index = (
            self.huidige_pdf_index + richting
        )

        if (
            0 <= nieuwe_index
            < self.totaal_pdf_paginas
        ):
            if self.huidige_pdf_anim:
                self.huidige_pdf_anim.stop(
                    self.pdf_scroll_view
                )

            self.scroll_pagina(
                nieuwe_index,
                self.totaal_pdf_paginas
            )

    def toggle_pauze(self, instance):
        if not self.pdf_is_pauze:
            self.pdf_is_pauze = True

            if self.huidige_pdf_anim:
                self.huidige_pdf_anim.stop(
                    self.pdf_scroll_view
                )

            instance.background_normal = self.asset_pad(
                "verder_knop.png"
            )

        else:
            self.pdf_is_pauze = False

            instance.background_normal = self.asset_pad(
                "pauze_knop.png"
            )

            resterende_duur = (
                self.pdf_scroll_view.scroll_y
                * self.scroll_snelheid_standaard
            )

            if resterende_duur > 0:
                self.huidige_pdf_anim = Animation(
                    scroll_y=0,
                    duration=resterende_duur,
                    t="linear"
                )

                self.huidige_pdf_anim.bind(
                    on_complete=self._pdf_anim_klaar
                )

                self.huidige_pdf_anim.start(
                    self.pdf_scroll_view
                )

    def sluit_pdf(self, *args):
        self.systeem_bezet = False
        self.pdf_is_pauze = False

        if self.huidige_pdf_anim:
            self.huidige_pdf_anim.stop(
                self.pdf_scroll_view
            )

            self.huidige_pdf_anim = None

        Animation(
            pos_hint={
                "center_x": 0.52,
                "y": -0.2
            },
            duration=0.5
        ).start(self.pdf_controls)

        Animation(
            opacity=0,
            duration=0.5
        ).start(self.pdf_scroll_view)

        Animation(
            opacity=1,
            duration=0.5
        ).start(self.ui)

        self.update_ui(
            "CHEMI",
            BG_STANDBY,
            KLEUR_TEKST_DONKER
        )

    # -----------------------------------------------------
    # MSDS EN STOFFENDATABASE
    # -----------------------------------------------------

    def automatische_map_scanner(self):
        while True:
            time.sleep(5)

            if self.nood_actief:
                continue

            try:
                nieuw_ontdekt = False

                if os.path.exists(MSDS_DIR):
                    for bestandsnaam in os.listdir(MSDS_DIR):
                        if not bestandsnaam.lower().endswith(
                            ".pdf"
                        ):
                            continue

                        stof_id = self.normaliseer_stofnaam(
                            os.path.splitext(bestandsnaam)[0]
                        )

                        if stof_id not in self.lab_database:
                            pdf_pad = os.path.join(
                                MSDS_DIR,
                                bestandsnaam
                            )

                            pdf_data = self.analyseer_msds_pdf(
                                pdf_pad
                            )

                            if pdf_data:
                                self.lab_database[
                                    stof_id
                                ] = pdf_data

                                nieuw_ontdekt = True

                if (
                    nieuw_ontdekt
                    and not self.systeem_bezet
                ):
                    self.log_status(
                        "DATABASE AUTOMATISCH BIJGEWERKT"
                    )

            except Exception as fout:
                print(f"Fout in mapscanner: {fout}")

    def normaliseer_stofnaam(self, tekst):
        tekst = str(tekst).lower().strip()

        return re.sub(
            r"[^a-z0-9]+",
            "",
            tekst
        )

    def analyseer_msds_pdf(self, pdf_pad):
        try:
            reader = PdfReader(pdf_pad)

            volledige_tekst = ""

            for pagina in reader.pages:
                pagina_tekst = pagina.extract_text()

                if pagina_tekst:
                    volledige_tekst += (
                        pagina_tekst + "\n"
                    )

            stofnaam = Path(pdf_pad).stem
            tekst_low = volledige_tekst.lower()

            # Gevarenpictogrammen
            gevonden_gevaren_pics = []

            r2_match = re.search(
                r"(rubriek|sectie|section)\s*2",
                tekst_low
            )

            r3_match = re.search(
                r"(rubriek|sectie|section)\s*3",
                tekst_low
            )

            rubriek2_blok = ""

            if (
                r2_match
                and r3_match
                and r2_match.start() < r3_match.start()
            ):
                rubriek2_blok = tekst_low[
                    r2_match.start():r3_match.start()
                ]

            zoek_gebied_gevaren = (
                rubriek2_blok
                if rubriek2_blok
                else tekst_low
            )

            ghs_mapping = {
                "ghs01": "explosief.png",
                "ghs02": "Brandbaar.png",
                "ghs03": "oxiderend.png",
                "ghs04": "gassen.png",
                "ghs05": "Corrosief.png",
                "ghs06": "giftig.png",
                "ghs07": "!.png",
                "ghs08": "ongezond.png",
                "ghs09": "milieu.png"
            }

            for ghs_code, afbeelding in ghs_mapping.items():
                if ghs_code in zoek_gebied_gevaren:
                    gevonden_gevaren_pics.append(
                        afbeelding
                    )

            pictogrammen_string = ",".join(
                gevonden_gevaren_pics
            )

            # PBM-informatie
            gevonden_pbm_pics = []
            gevonden_pbm = []

            r8_match = re.search(
                r"(rubriek|sectie|section|hoofdstuk)\s*8",
                tekst_low
            )

            r9_match = re.search(
                r"(rubriek|sectie|section|hoofdstuk)\s*9",
                tekst_low
            )

            pbm_blok = ""

            if (
                r8_match
                and r9_match
                and r8_match.start() < r9_match.start()
            ):
                pbm_blok = tekst_low[
                    r8_match.start():r9_match.start()
                ]

            zoek_gebied_pbm = (
                pbm_blok
                if pbm_blok
                else tekst_low
            )

            if any(
                term in zoek_gebied_pbm
                for term in [
                    "bril",
                    "oog",
                    "gelaat",
                    "en 166",
                    "en166"
                ]
            ):
                gevonden_pbm.append(
                    "een veiligheidsbril"
                )
                gevonden_pbm_pics.append(
                    "bril.png"
                )

            if any(
                term in zoek_gebied_pbm
                for term in [
                    "handschoen",
                    "nitril",
                    "rubber",
                    "en 374",
                    "en374"
                ]
            ):
                gevonden_pbm.append(
                    "chemiebestendige handschoenen"
                )
                gevonden_pbm_pics.append(
                    "handschoenen.png"
                )

            if any(
                term in zoek_gebied_pbm
                for term in [
                    "masker",
                    "ademhaling",
                    "filter",
                    "ffp"
                ]
            ):
                gevonden_pbm.append(
                    "ademhalingsbescherming"
                )
                gevonden_pbm_pics.append(
                    "masker.png"
                )

            if any(
                term in zoek_gebied_pbm
                for term in [
                    "schort",
                    "overall",
                    "pak",
                    "en 13034"
                ]
            ):
                gevonden_pbm.append(
                    "beschermende kleding"
                )
                gevonden_pbm_pics.append(
                    "schort.png"
                )

            if any(
                term in zoek_gebied_pbm
                for term in [
                    "schoen",
                    "laars",
                    "schoeisel",
                    "en 20345"
                ]
            ):
                gevonden_pbm.append(
                    "veiligheidsschoenen"
                )
                gevonden_pbm_pics.append(
                    "schoenen.png"
                )

            if gevonden_pbm:
                pbm_tekst = (
                    "Draag in ieder geval: "
                    + ", ".join(gevonden_pbm)
                    + "."
                )
            else:
                pbm_tekst = (
                    "Draag de standaard "
                    "beschermingsmiddelen."
                )

            pbm_pics_string = ",".join(
                gevonden_pbm_pics
            )

            oog_tekst = (
                "Bij contact met de ogen, direct spoelen "
                "met overvloedig water en een arts "
                "raadplegen."
            )

            gevaren_tekst = (
                "Zie het veiligheidsblad voor de "
                "specifieke gevaren."
            )

            return {
                "naam": stofnaam,
                "pbm_lab": pbm_tekst,
                "pbm_fabriek": pbm_tekst,
                "pbm_pic_lab": pbm_pics_string,
                "pbm_pic_fabriek": pbm_pics_string,
                "pictogram": pictogrammen_string,
                "n_ogen": oog_tekst,
                "msds": Path(pdf_pad).name,
                "gevaren": gevaren_tekst,
                "volledige_tekst": volledige_tekst
            }

        except Exception as fout:
            print(
                f"Fout bij uitlezen PDF {pdf_pad}: {fout}"
            )
            return None

    def laad_stoffen(self):
        database = {}

        # Eerst CSV-bestand laden.
        if os.path.exists(STOFFEN_CSV):
            try:
                with open(
                    STOFFEN_CSV,
                    mode="r",
                    encoding="utf-8-sig"
                ) as bestand:
                    eerste_regel = bestand.readline()

                    scheidingsteken = (
                        ";"
                        if ";" in eerste_regel
                        else ","
                    )

                    bestand.seek(0)

                    reader = csv.DictReader(
                        bestand,
                        delimiter=scheidingsteken
                    )

                    for rij in reader:
                        schone_rij = {
                            str(k).strip().lower():
                                str(v).strip()
                            for k, v in rij.items()
                            if k is not None
                            and v is not None
                        }

                        if not schone_rij:
                            continue

                        naam = schone_rij.get("stof", "")

                        if not naam:
                            naam = next(
                                iter(schone_rij.values()),
                                ""
                            )

                        if not naam:
                            continue

                        stof_id = self.normaliseer_stofnaam(
                            naam
                        )

                        database[stof_id] = {
                            "naam": naam,
                            "pbm_lab": schone_rij.get(
                                "pbm_lab",
                                ""
                            ),
                            "pbm_fabriek": schone_rij.get(
                                "pbm_fabriek",
                                ""
                            ),
                            "pbm_pic_lab": schone_rij.get(
                                "pbm_pic_lab",
                                ""
                            ),
                            "pbm_pic_fabriek": schone_rij.get(
                                "pbm_pic_fabriek",
                                ""
                            ),
                            "pictogram": schone_rij.get(
                                "pictogram",
                                ""
                            ),
                            "n_ogen": next(
                                (
                                    waarde
                                    for sleutel, waarde
                                    in schone_rij.items()
                                    if "ogen" in sleutel
                                ),
                                ""
                            ),
                            "msds": schone_rij.get(
                                "msds",
                                ""
                            ),
                            "gevaren": schone_rij.get(
                                "gevaren",
                                (
                                    "Er zijn geen specifieke "
                                    "gevaren bekend."
                                )
                            )
                        }

            except Exception as fout:
                print(f"Fout bij laden CSV: {fout}")

        # Daarna MSDS-map scannen.
        if os.path.exists(MSDS_DIR):
            try:
                for bestandsnaam in os.listdir(MSDS_DIR):
                    if not bestandsnaam.lower().endswith(
                        ".pdf"
                    ):
                        continue

                    stof_id = self.normaliseer_stofnaam(
                        os.path.splitext(bestandsnaam)[0]
                    )

                    if stof_id not in database:
                        pdf_pad = os.path.join(
                            MSDS_DIR,
                            bestandsnaam
                        )

                        pdf_data = self.analyseer_msds_pdf(
                            pdf_pad
                        )

                        if pdf_data:
                            database[stof_id] = pdf_data

            except Exception as fout:
                print(
                    f"MSDS-map kon niet worden gelezen: {fout}"
                )

        print(
            f"Aantal geladen stoffen: {len(database)}"
        )

        return database

    def vind_beste_stof(self, opdracht):
        if not opdracht:
            return None

        stopwoorden = [
            "wat",
            "zijn",
            "de",
            "het",
            "van",
            "gevaar",
            "gevaren",
            "risico",
            "pbm",
            "informatie",
            "msds",
            "blad",
            "laat",
            "zien"
        ]

        woorden = re.findall(
            r"[a-zA-Z0-9À-ÿ]+",
            opdracht.lower()
        )

        gefilterde_woorden = [
            woord
            for woord in woorden
            if woord not in stopwoorden
        ]

        database_ids = list(
            self.lab_database.keys()
        )

        # Eerst volledige combinatie proberen.
        combinatie = self.normaliseer_stofnaam(
            " ".join(gefilterde_woorden)
        )

        exacte_matches = [
            stof_id
            for stof_id in database_ids
            if combinatie in stof_id
            or stof_id in combinatie
        ]

        if exacte_matches:
            return exacte_matches[0]

        # Daarna per woord fuzzy matching.
        for woord in gefilterde_woorden:
            genormaliseerd = self.normaliseer_stofnaam(
                woord
            )

            matches = difflib.get_close_matches(
                genormaliseerd,
                database_ids,
                n=1,
                cutoff=0.6
            )

            if matches:
                return matches[0]

        return None

    def lees_gevaren_voor(self, info):
        self.systeem_bezet = True

        gevaren_tekst = info.get(
            "gevaren",
            (
                "Er zijn geen specifieke gevaren "
                "bekend voor deze stof."
            )
        )

        self.update_ui(
            f"GEVAREN: {info.get('naam', '')}",
            "#FF4500",
            "#FFFFFF",
            info.get("pictogram", "")
        )

        tekst = (
            f"De gevaren van "
            f"{info.get('naam', 'deze stof')} zijn: "
            f"{gevaren_tekst}"
        )

        self.assistent_spreekt(tekst)

        time.sleep(4)

        self.systeem_bezet = False

        self.update_ui(
            "CHEMI",
            BG_STANDBY,
            KLEUR_TEKST_DONKER
        )

    def open_msds(self, info):
        pdf_naam = info.get("msds", "")

        if not pdf_naam:
            self.assistent_spreekt(
                "Er is geen veiligheidsblad "
                "gekoppeld aan deze stof."
            )
            return

        pdf_pad = os.path.join(
            MSDS_DIR,
            pdf_naam
        )

        if os.path.exists(pdf_pad):
            Clock.schedule_once(
                lambda dt, pad=pdf_pad:
                    self.toon_pdf_in_app(pad)
            )
        else:
            self.assistent_spreekt(
                "Het veiligheidsblad is niet gevonden."
            )

    # -----------------------------------------------------
    # OPSCHONEN
    # -----------------------------------------------------

    def schoonmaak_bij_opstart(self):
        try:
            if os.path.exists(self.TEMP_PDF_DIR):
                for bestandsnaam in os.listdir(
                    self.TEMP_PDF_DIR
                ):
                    bestand_pad = os.path.join(
                        self.TEMP_PDF_DIR,
                        bestandsnaam
                    )

                    if os.path.isfile(bestand_pad):
                        try:
                            os.remove(bestand_pad)
                        except OSError:
                            pass

            self.log_status(
                "TIJDELIJKE BESTANDEN OPGESCHOOND"
            )

        except Exception as fout:
            print(f"Opschoonfout: {fout}")


# ---------------------------------------------------------
# APPLICATIE STARTEN
# ---------------------------------------------------------

if __name__ == "__main__":
    ChemieApp().run()
