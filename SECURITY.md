# Security policy

Chromecast Web has **no authentication**: anyone who can open the page can control the Chromecast, browse the local
media folder and make the server fetch content. Its stream proxy, `yt-dlp` resolver and remote headless browser
fetch **arbitrary URLs** on behalf of the client. Run it **only on your home LAN or behind a VPN** and **never expose
it to the internet** (no port forwarding, no public reverse proxy, no public Coolify domain).

Please report vulnerabilities **privately** through GitHub: *Security › Report a vulnerability* on this repository.
Do not open public issues for security problems.

- Supported: the latest release.
- Never paste public URLs or IPs of your server, tokens, stream credentials or personal playlists in issues or
  screenshots.
- Expect a first answer within 7 days.
