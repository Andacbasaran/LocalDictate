# LocalDictate

%100 offline, 0 MB VRAM, ultra düşük gecikmeli masaüstü sesli yazma (speech-to-text) aracı — açık kaynaklı ve gizlilik odaklı Wispr Flow alternatifi.

## Özellikler (MVP)
- **Global Kısayol:** Hem **Aç-Kapa (Toggle)** (`Ctrl+Alt+Space`) hem **Bas-Konuş (Push-to-Talk)** (`Sağ Ctrl` / `F9`) desteği + kayıt sırasında `Esc` ile iptal
- **Lokal AI Motoru:** `faster-whisper` (CTranslate2 INT8 CPU — 0 MB VRAM) + Silero VAD sessizlik filtresi ile Türkçe ve İngilizce deşifre
- **Yüzen Mini Gösterge (Overlay):** Odağı çalmayan (no-focus-steal), canlı ses dalgası ve durum göstergeli PyQt6 HUD
- **Sistem Tepsisi & Ayarlar:** Model (`tiny` → `large-v3-turbo`), dil (`Otomatik / TR / EN`), mikrofon ve kısayol yönetimi
- **Otomatik Yapıştırma:** Önceki panoyu koruyan Win32 `SendInput` (`Ctrl+V`) ile imlecin bulunduğu aktif pencereye anında Unicode metin aktarımı

## Kurulum ve Çalıştırma

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe run.py
```

İlk açılışta seçili Whisper modeli (`small`, ~465 MB) otomatik olarak yerel önbelleğe indirilir; sonraki açılışlarda tamamen çevrimdışı çalışır.

## Testler

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

## Yol Haritası
- [x] Çekirdek MVP (Kayıt + Silero VAD + faster-whisper INT8 + Overlay + System Tray + Win32 Yapıştırma)
- [ ] Opsiyonel lokal LLM (Ollama) ile noktalama ve metin temizleme katmanı
- [ ] PyInstaller / Inno Setup + Portable ZIP dağıtım paketi
