from kivy.clock import Clock
from kivy.utils import platform


if platform == "android":
    try:
        from android.runnable import run_on_ui_thread
    except ImportError:
        def run_on_ui_thread(function):
            return function
else:
    def run_on_ui_thread(function):
        return function


class AndroidContinuousListener:
    """Continu herstartende Android SpeechRecognizer."""

    def __init__(self, on_text, on_status=None, on_error=None, language="nl-NL"):
        self.on_text = on_text
        self.on_status = on_status
        self.on_error = on_error
        self.language = language

        self.recognizer = None
        self.listener = None
        self.intent = None

        self.actief = False
        self.luistert = False
        self.herstart_event = None
        self.watchdog_event = None
        self.callback_ontvangen = False
        self.android_klassen_geladen = False

        if platform == "android":
            self._laad_android_klassen()

    def _laad_android_klassen(self):
        try:
            from jnius import autoclass, PythonJavaClass, java_method

            self.PythonJavaClass = PythonJavaClass
            self.java_method = java_method
            self.PythonActivity = autoclass("org.kivy.android.PythonActivity")
            self.SpeechRecognizer = autoclass("android.speech.SpeechRecognizer")
            self.RecognizerIntent = autoclass("android.speech.RecognizerIntent")
            self.Intent = autoclass("android.content.Intent")
            self.android_klassen_geladen = True
            print("[ANDROID LISTENER]: Android spraakklassen geladen")
        except Exception as fout:
            self.android_klassen_geladen = False
            self._fout(f"Android spraakklassen konden niet worden geladen: {fout}")

    def start(self):
        if platform != "android":
            self._status("ANDROID-LUISTERAAR NIET BESCHIKBAAR")
            return
        if not self.android_klassen_geladen:
            self._fout("ANDROID SPRAAKKLASSEN ZIJN NIET GELADEN")
            return
        if self.actief:
            return

        self.actief = True
        self._status("MICROFOON INITIALISEREN...")
        self._maak_en_start()

    @run_on_ui_thread
    def _maak_en_start(self, *args):
        if not self.actief:
            return

        try:
            activiteit = self.PythonActivity.mActivity
            if activiteit is None:
                self._fout("ANDROID ACTIVITY NIET BESCHIKBAAR")
                self._plan_herstart(2.0)
                return

            if not self.SpeechRecognizer.isRecognitionAvailable(activiteit):
                self._fout("SPRAAKHERKENNING NIET BESCHIKBAAR OP DIT APPARAAT")
                return

            if self.recognizer is None:
                self._status("SPRAAKHERKENNER AANMAKEN...")
                self.recognizer = self.SpeechRecognizer.createSpeechRecognizer(activiteit)

            if self.listener is None:
                self._maak_listener()

            if self.listener is None:
                self._fout("RECOGNITION LISTENER KON NIET WORDEN AANGEMAAKT")
                self._plan_herstart(2.0)
                return

            self.recognizer.setRecognitionListener(self.listener)

            # Eenvoudige intent voor compatibiliteit met oudere Samsung-tablets.
            self.intent = self.Intent(self.RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            self.intent.putExtra(
                self.RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                self.RecognizerIntent.LANGUAGE_MODEL_FREE_FORM
            )
            self.intent.putExtra(
                self.RecognizerIntent.EXTRA_LANGUAGE,
                "nl-NL"
            )
            
            self.intent.putExtra(
                "android.speech.extra.LANGUAGE",
                "nl-NL"
            )

            self.callback_ontvangen = False
            print("[ANDROID LISTENER]: STARTLISTENING VERSTUREN")
            self.recognizer.startListening(self.intent)
            print("[ANDROID LISTENER]: STARTLISTENING VERSTUURD")

            self.luistert = True
            self._status("MICROFOON START...")

            # Watchdog tijdelijk uitgeschakeld.
            # Op deze oudere tablet veroorzaakt cancel/herstart
            # een beëindiging van het Python-proces.
            print(
                "[ANDROID LISTENER]: "
                "WACHT OP CALLBACK ZONDER AUTOMATISCHE HERSTART"
            )

        except Exception as fout:
            self.luistert = False
            self._fout(f"Microfoon kon niet starten: {fout}")
            self._plan_herstart(2.0)

    def _maak_listener(self):
        try:
            eigenaar = self
            PythonJavaClass = self.PythonJavaClass
            java_method = self.java_method

            class RecognitionListener(PythonJavaClass):
                __javainterfaces__ = ["android/speech/RecognitionListener"]
                __javacontext__ = "app"

                @java_method("(Landroid/os/Bundle;)V")
                def onReadyForSpeech(listener_self, params):
                    eigenaar._markeer_callback("onReadyForSpeech")
                    eigenaar.luistert = True
                    eigenaar._status("MICROFOON ACTIEF - ZEG CHEMI")

                @java_method("()V")
                def onBeginningOfSpeech(listener_self):
                    eigenaar._markeer_callback("onBeginningOfSpeech")
                    eigenaar._status("SPRAAK GEHOORD")

                @java_method("(F)V")
                def onRmsChanged(listener_self, rms_db):
                    # Ook deze callback bewijst dat de listener gekoppeld is.
                    eigenaar.callback_ontvangen = True

                @java_method("([B)V")
                def onBufferReceived(listener_self, buffer):
                    eigenaar._markeer_callback("onBufferReceived")

                @java_method("()V")
                def onEndOfSpeech(listener_self):
                    eigenaar._markeer_callback("onEndOfSpeech")
                    eigenaar.luistert = False
                    eigenaar._status("SPRAAK VERWERKEN...")

                @java_method("(Landroid/os/Bundle;)V")
                def onResults(listener_self, results):
                    eigenaar._markeer_callback("onResults")
                    eigenaar.luistert = False
                    eigenaar._verwerk_bundle(results, definitief=True)

                @java_method("(Landroid/os/Bundle;)V")
                def onPartialResults(listener_self, partial_results):
                    eigenaar._markeer_callback("onPartialResults")
                    eigenaar._verwerk_bundle(partial_results, definitief=False)

                @java_method("(I)V")
                def onError(listener_self, error_code):
                    eigenaar._markeer_callback(f"onError code={error_code}")
                    eigenaar.luistert = False
                    eigenaar._verwerk_fout(error_code)

                @java_method("(ILandroid/os/Bundle;)V")
                def onEvent(listener_self, event_type, params):
                    eigenaar._markeer_callback(f"onEvent type={event_type}")

            self.listener = RecognitionListener()
            print("[ANDROID LISTENER]: RecognitionListener aangemaakt")

        except Exception as fout:
            self.listener = None
            self._fout(f"RecognitionListener kon niet worden aangemaakt: {fout}")

    def _markeer_callback(self, naam):
        self.callback_ontvangen = True
        print(f"[ANDROID CALLBACK]: {naam}")

    def _controleer_callback(self, dt=None):
        self.watchdog_event = None

        if not self.actief:
            return

        if self.callback_ontvangen:
            print("[ANDROID WATCHDOG]: Callback is ontvangen")
            return

        print("[ANDROID WATCHDOG]: Geen SpeechRecognizer-callback ontvangen")
        self._status("GEEN REACTIE VAN SPRAAKHERKENNER - HERSTARTEN")
        self._plan_herstart(0.5)

    def _annuleer_watchdog(self):
        if self.watchdog_event is not None:
            try:
                self.watchdog_event.cancel()
            except Exception:
                pass
            self.watchdog_event = None

    def _verwerk_bundle(self, bundle, definitief=False):
        try:
            resultaten = bundle.getStringArrayList(
                self.SpeechRecognizer.RESULTS_RECOGNITION
            )

            if resultaten is None or resultaten.size() == 0:
                if definitief:
                    self._plan_herstart(0.5)
                return

            tekst = str(resultaten.get(0)).strip()
            if not tekst:
                if definitief:
                    self._plan_herstart(0.5)
                return

            soort = "DEFINITIEF" if definitief else "DEELS"
            print(f"[ANDROID SPRAAK {soort}]: {tekst}")

            if definitief:
                Clock.schedule_once(
                    lambda dt, resultaat=tekst: self.on_text(resultaat), 0
                )
                self._plan_herstart(0.8)

        except Exception as fout:
            self._fout(f"Spraakresultaat kon niet worden verwerkt: {fout}")
            self._plan_herstart(1.0)

    def _verwerk_fout(self, error_code):
        try:
            code = int(error_code)
        except Exception:
            code = -1

        foutnamen = {
            1: "NETWERK TIME-OUT",
            2: "NETWERKFOUT",
            3: "AUDIOFOUT",
            4: "SERVERFOUT",
            5: "CLIENTFOUT",
            6: "GEEN SPRAAK GEHOORD",
            7: "GEEN OVEREENKOMST",
            8: "HERKENNER BEZET",
            9: "GEEN MICROFOONRECHT",
            10: "TE VEEL AANVRAGEN",
            11: "SERVER VERBROKEN",
            12: "TAAL NIET BESCHIKBAAR",
            13: "TAAL NIET ONDERSTEUND"
        }
        foutnaam = foutnamen.get(code, f"ONBEKENDE FOUT {code}")
        print(f"[ANDROID LISTENER FOUTCODE]: {code} - {foutnaam}")

        if code in (6, 7):
            self._status("MICROFOON HERSTART...")
            wachttijd = 0.5
        elif code == 8:
            self._status("SPRAAKHERKENNER BEZET")
            wachttijd = 1.5
        elif code == 9:
            self._fout("MICROFOONTOESTEMMING ONTBREEKT")
            wachttijd = 5.0
        elif code in (1, 2, 4, 11):
            self._fout(foutnaam)
            wachttijd = 3.0
        elif code == 10:
            self._fout(foutnaam)
            wachttijd = 5.0
        else:
            self._fout(foutnaam)
            wachttijd = 2.0

        print("[ANDROID TEST\]: HERSTART OVERGESLAGEN")

    def _plan_herstart(self, wachttijd=0.5):
        if not self.actief:
            return

        self._annuleer_watchdog()

        if self.herstart_event is not None:
            try:
                self.herstart_event.cancel()
            except Exception:
                pass

        self.herstart_event = Clock.schedule_once(self._herstart, wachttijd)

    @run_on_ui_thread
    def _herstart(self, *args):
        self.herstart_event = None

        if not self.actief:
            return

        try:
            if self.recognizer is not None:
                self.recognizer.cancel()
        except Exception as fout:
            print(f"[ANDROID LISTENER]: Annuleren gaf melding: {fout}")

        Clock.schedule_once(lambda dt: self._maak_en_start(), 0.3)

    def pauzeer(self):
        self.actief = False
        self.luistert = False
        self._annuleer_watchdog()

        if self.herstart_event is not None:
            try:
                self.herstart_event.cancel()
            except Exception:
                pass
            self.herstart_event = None

        self._pauzeer_op_ui_thread()

    @run_on_ui_thread
    def _pauzeer_op_ui_thread(self):
        try:
            if self.recognizer is not None:
                self.recognizer.cancel()
        except Exception as fout:
            print(f"Microfoon pauzeren gaf melding: {fout}")
        self._status("MICROFOON GEPAUZEERD")

    def hervat(self):
        if self.actief:
            return
        self.actief = True
        self._status("MICROFOON HERVATTEN...")
        Clock.schedule_once(lambda dt: self._maak_en_start(), 0.3)

    def stop(self):
        self.actief = False
        self.luistert = False
        self._annuleer_watchdog()

        if self.herstart_event is not None:
            try:
                self.herstart_event.cancel()
            except Exception:
                pass
            self.herstart_event = None

        self._stop_op_ui_thread()

    @run_on_ui_thread
    def _stop_op_ui_thread(self):
        try:
            if self.recognizer is not None:
                self.recognizer.cancel()
                self.recognizer.destroy()
        except Exception as fout:
            print(f"SpeechRecognizer kon niet netjes worden afgesloten: {fout}")

        self.recognizer = None
        self.listener = None
        self.intent = None
        self._status("MICROFOON UIT")

    def _status(self, tekst):
        print(f"[ANDROID LISTENER]: {tekst}")
        if self.on_status is not None:
            Clock.schedule_once(
                lambda dt, status=tekst: self.on_status(status), 0
            )

    def _fout(self, tekst):
        print(f"[ANDROID LISTENER FOUT]: {tekst}")
        if self.on_error is not None:
            Clock.schedule_once(
                lambda dt, fouttekst=tekst: self.on_error(fouttekst), 0
            )
