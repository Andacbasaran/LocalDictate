# LocalDictate

%100 offline, 0 MB VRAM, ultra düşük gecikmeli masaüstü sesli yazma (speech-to-text) aracı — açık kaynaklı ve gizlilik odaklı Wispr Flow alternatifi.

## Özellikler
- **Global Kısayol:** Hem **Aç-Kapa (Toggle)** (`Ctrl+Alt+Space`) hem **Bas-Konuş (Push-to-Talk)** (`Sağ Ctrl` / `F9`) desteği + kayıt sırasında `Esc` ile anında iptal
- **Lokal AI Motoru:** `faster-whisper` (CTranslate2 INT8 CPU — 0 MB VRAM) + Silero VAD sessizlik filtresi ile Türkçe, İngilizce ve çoklu dil deşifresi
- **Opsiyonel Lokal LLM (Ollama):** Noktalama, dolgu kelimesi temizleme ve stil dönüştürme (`Temizleme`, `Kurumsal`, `Kısa & Öz`, `Teknik / Kod`) — Ollama kapalıysa ham metne kesintisiz fallback
- **Kişisel Sözlük & Akıllı Kısaltmalar:** Özel kelimelerle Whisper `initial_prompt` yönlendirmesi ve otomatik kelime/metin değiştirme kuralları (`eski -> yeni`)
- **Yüzen Mini Gösterge (Overlay):** Win32 `WS_EX_NOACTIVATE` ile aktif pencerenin odağını asla çalmayan, canlı 10 çubuklu ses dalgası ve durum göstergeli PyQt6 HUD
- **Dikte Geçmişi & İstatistikler:** Tamamen yerel SQLite geçmiş arşivi, anlık arama, tek tıkla kopyalama, toplam kelime ve tahmini zaman kazancı kartları
- **Sesli Geri Bildirim & Otomatik Başlatma:** Yumuşak başlangıç/bitiş ses efektleri, sistem tepsisinden son dikteyi kopyalama ve Windows başlangıcında otomatik çalıştırma
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

## Windows `.exe` Paketleme

```powershell
.\scripts\build_exe.ps1
```
Çıktı `dist\LocalDictate\LocalDictate.exe` konumunda oluşturulur.
