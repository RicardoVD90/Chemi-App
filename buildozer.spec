[app]
title = ChemieApp
package.name = chemieapp
package.domain = org.chemie

source.dir = .

source.include_exts = py,png,jpg,kv,atlas,wav,mp3
version = 0.1

# BELANGRIJK: Alle bibliotheken die jouw app gebruikt
requirements = python3,kivy,pygame,pypdf,requests,certifi,urllib3,idna,charset-normalizer,pyjnius

# Rechten voor de Android tablet
android.permissions = RECORD_AUDIO,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

orientation = landscape
fullscreen = 1

# Automatisch akkoord geven op de Android SDK licentievoorwaarden
android.accept_sdk_license = True

# Doel-API en NDK versies vastzetten voor een stabiele download
android.api = 33
android.minapi = 21
android.ndk = 25b

# Log niveau (0 = info, 1 = debug, 2 = debug met alle details)
log_level = 2
