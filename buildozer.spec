[app]

title = ChemieApp
package.name = chemieapp
package.domain = org.chemie

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,wav,mp3,pdf,json,txt

version = 0.1

requirements = python3==3.10.11,hostpython3==3.10.11,kivy,pypdf,requests,pyjnius

orientation = landscape
fullscreen = 1

android.permissions = RECORD_AUDIO,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

android.accept_sdk_license = True

android.api = 33
android.minapi = 21
android.ndk = 25b

android.archs = arm64-v8a, armeabi-v7a

log_level = 2
warn_on_root = 1
