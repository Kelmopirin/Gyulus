import yt_dlp

def download_video(url: str):
    # Beállítások testreszabása
    ydl_opts = {
        # A legjobb videó és audio sáv összeillesztése MP4 formátumban
        'format': 'bestvideo+bestaudio/best',
        'merge_output_format': 'mp4',
        # Mentési név formátuma: Cím.kiterjesztés
        'outtmpl': '%(title)s.%(ext)s',
        # Csendes mód kikapcsolása, hogy lássuk a haladást
        'quiet': False,
        'no_warnings': True,
    }

    try:
        print(f"Letöltés indítása: {url}")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print("\nA letöltés sikeresen befejeződött!")
    except Exception as e:
        print(f"\nHiba történt a letöltés során: {e}")

if __name__ == "__main__":
    # Cseréld ki a kívánt YouTube videó hivatkozására
    video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    download_video(video_url)