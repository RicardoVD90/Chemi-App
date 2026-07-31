[app]
title = ChemieApp
package.name = chemieapp
package.domain = org.chemie

source.dir = .

source.include_exts = py,png,jpg,kv,atlas,wav,mp3
version = 0.1

# BELANGRIJK: Alle bibliotheken die jouw app gebruikt
requirements = python3,kivy,pygame,edge-tts,SpeechRecognition,pypdf,pymupdf,requests,certifi,urllib3,idna,charset-normalizer,idna

# Rechten voor de Android tablet
android.permissions = RECORD_AUDIO,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

orientation = landscape
fullscreen = 1
