import json
import os
import re
import threading
from pathlib import Path

from kivy.utils import platform


class AndroidPdfRenderCache:
    """Rendert PDF-pagina's via Android PdfRenderer en bewaart ze als PNG-cache."""

    def __init__(self, cache_root, schaal=1.5, logger=print):
        self.cache_root = cache_root
        self.schaal = schaal
        self.log = logger
        self.lock = threading.Lock()
        os.makedirs(self.cache_root, exist_ok=True)

    def _veilige_naam(self, naam):
        veilig = re.sub(r"[^a-zA-Z0-9_-]+", "_", str(naam)).strip("_")
        return veilig or "document"

    def _map(self, pdf_pad):
        return os.path.join(self.cache_root, self._veilige_naam(Path(pdf_pad).stem))

    def _manifest(self, pdf_pad):
        return os.path.join(self._map(pdf_pad), "manifest.json")

    def is_actueel(self, pdf_pad):
        try:
            with open(self._manifest(pdf_pad), "r", encoding="utf-8") as bestand:
                data = json.load(bestand)
            stat = os.stat(pdf_pad)
            aantal = int(data.get("pagina_aantal", 0))
            if data.get("pdf_grootte") != stat.st_size:
                return False
            if data.get("pdf_mtime") != int(stat.st_mtime):
                return False
            if aantal <= 0:
                return False
            return all(
                os.path.exists(os.path.join(self._map(pdf_pad), f"page_{i + 1:03d}.png"))
                for i in range(aantal)
            )
        except Exception:
            return False

    def pagina_paden(self, pdf_pad):
        if not self.is_actueel(pdf_pad):
            return []
        with open(self._manifest(pdf_pad), "r", encoding="utf-8") as bestand:
            aantal = int(json.load(bestand)["pagina_aantal"])
        return [
            os.path.join(self._map(pdf_pad), f"page_{i + 1:03d}.png")
            for i in range(aantal)
        ]

    def render(self, pdf_pad):
        if platform != "android":
            self.log("[PDF RENDER FOUT]: Android PdfRenderer is alleen op Android beschikbaar")
            return []

        with self.lock:
            bestaand = self.pagina_paden(pdf_pad)
            if bestaand:
                self.log(f"[PDF CACHE]: {len(bestaand)} PAGINA'S BESCHIKBAAR")
                return bestaand

            from jnius import autoclass

            File = autoclass("java.io.File")
            FileOutputStream = autoclass("java.io.FileOutputStream")
            ParcelFileDescriptor = autoclass("android.os.ParcelFileDescriptor")
            PdfRenderer = autoclass(
                "android.graphics.pdf.PdfRenderer"
            )
            
            PdfRendererPage = autoclass(
                "android.graphics.pdf.PdfRenderer$Page"
            )
            
            Bitmap = autoclass(
                "android.graphics.Bitmap"
            )
            
            BitmapConfig = autoclass(
                "android.graphics.Bitmap$Config"
            )
            
            CompressFormat = autoclass(
                "android.graphics.Bitmap$CompressFormat"
            )

            doelmap = self._map(pdf_pad)
            os.makedirs(doelmap, exist_ok=True)
            for naam in os.listdir(doelmap):
                if naam.startswith("page_") and naam.endswith(".png"):
                    try:
                        os.remove(os.path.join(doelmap, naam))
                    except OSError:
                        pass

            descriptor = None
            renderer = None
            try:
                descriptor = ParcelFileDescriptor.open(
                    File(pdf_pad), ParcelFileDescriptor.MODE_READ_ONLY
                )
                renderer = PdfRenderer(descriptor)
                aantal = renderer.getPageCount()
                self.log(f"[PDF RENDER]: START {os.path.basename(pdf_pad)} - {aantal} PAGINA'S")

                for index in range(aantal):
                    pagina = renderer.openPage(index)
                    bitmap = None
                    uitvoer = None
                    try:
                        breedte = max(1, int(pagina.getWidth() * self.schaal))
                        hoogte = max(1, int(pagina.getHeight() * self.schaal))
                        bitmap = Bitmap.createBitmap(breedte, hoogte, BitmapConfig.ARGB_8888)
                        bitmap.eraseColor(-1)
                        pagina.render(
                            bitmap,
                            None,
                            None,
                            PdfRendererPage.RENDER_MODE_FOR_DISPLAY
                        )
                        png_pad = os.path.join(doelmap, f"page_{index + 1:03d}.png")
                        uitvoer = FileOutputStream(png_pad)
                        bitmap.compress(CompressFormat.PNG, 100, uitvoer)
                        uitvoer.flush()
                        self.log(f"[PDF RENDER]: PAGINA {index + 1}/{aantal} KLAAR")
                    finally:
                        if uitvoer is not None:
                            try:
                                uitvoer.close()
                            except Exception:
                                pass
                    
                        if bitmap is not None:
                            try:
                                bitmap.recycle()
                            except Exception:
                                pass
                    
                        try:
                            pagina.close()
                        except Exception:
                            pass

                stat = os.stat(pdf_pad)
                with open(self._manifest(pdf_pad), "w", encoding="utf-8") as bestand:
                    json.dump({
                        "pdf_grootte": stat.st_size,
                        "pdf_mtime": int(stat.st_mtime),
                        "pagina_aantal": aantal,
                    }, bestand)
                resultaat = self.pagina_paden(pdf_pad)
                self.log(f"[PDF RENDER]: KLAAR - {len(resultaat)} PAGINA'S")
                return resultaat
            except Exception as fout:
                self.log(f"[PDF RENDER FOUT]: {type(fout).__name__}: {fout}")
                return []
            finally:
                if renderer is not None:
                    renderer.close()
                if descriptor is not None:
                    descriptor.close()

    def render_alle(self, msds_map):
        pdfs = [
            os.path.join(msds_map, naam)
            for naam in sorted(os.listdir(msds_map))
            if naam.lower().endswith(".pdf")
        ]
        self.log(f"[PDF RENDER ALLES]: {len(pdfs)} PDF'S CONTROLEREN")
        for nummer, pdf_pad in enumerate(pdfs, 1):
            if self.is_actueel(pdf_pad):
                self.log(f"[PDF RENDER ALLES]: {nummer}/{len(pdfs)} CACHE OK")
            else:
                self.log(f"[PDF RENDER ALLES]: {nummer}/{len(pdfs)} {os.path.basename(pdf_pad)}")
                self.render(pdf_pad)
        self.log("[PDF RENDER ALLES]: KLAAR")
