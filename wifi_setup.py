import network
import socket
import time
from config_manager import save_config
import machine

def start_ap():
    ap = network.WLAN(network.AP_IF)
    ap.config(essid="PowerTrack_AP", password="powertrack123")
    ap.active(True)
    while not ap.active():
        time.sleep(1)
    print("✅ AP lancé sur :", ap.ifconfig())

def start_webserver():
    html_form = """\
<!DOCTYPE html>
<html>
  <head><meta charset="UTF-8"><title>Configurer</title></head>
  <body>
    <h2>⚙️ Configurer votre multiprise</h2>
    <form method="POST">
      <label>SSID:</label><br>
      <input name="ssid"><br><br>
      <label>Mot de passe Wi-Fi:</label><br>
      <input name="password" type="password"><br><br>
      <label>Device ID:</label><br>
      <input name="deviceid"><br><br>
      <input type="submit" value="Enregistrer">
    </form>
  </body>
</html>
"""

    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)
    print("🌐 Portail ouvert sur http://192.168.4.1")

    while True:
        try:
            cl, addr = s.accept()
            print("📲 Client connecté :", addr)
            request = cl.recv(1024).decode("utf-8")

            if "POST" in request:
                try:
                    content_length = 0
                    lines = request.split("\r\n")
                    for line in lines:
                        if "Content-Length:" in line:
                            content_length = int(line.split(":")[1].strip())

                    print("📏 Content-Length:", content_length)

                    if "\r\n\r\n" in request:
                        parts = request.split("\r\n\r\n", 1)
                        body = parts[1]
                        while len(body) < content_length:
                            body += cl.recv(1024).decode("utf-8")
                    else:
                        body = cl.recv(content_length).decode("utf-8")

                    print("📥 Données brutes :", body)

                    fields = {}
                    for pair in body.split("&"):
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            fields[k] = v

                    print("✅ Champs extraits :", fields)

                    if all(k in fields for k in ("ssid", "password", "deviceid")):
                        config = {
                            "ssid": fields["ssid"],
                            "password": fields["password"],
                            "deviceId": fields["deviceid"],
                            "deviceSecret": ""  # sera rempli plus tard automatiquement
                        }

                        save_config(config)

                        cl.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n")
                        cl.send("<html><body><h3>✅ Configuration enregistrée</h3><p>Redémarrage...</p></body></html>")
                        cl.close()

                        print("✅ Configuration terminée. Redémarrez manuellement votre multiprise.")
                        while True:
                            time.sleep(1)

                    else:
                        raise ValueError("Champs manquants")

                except Exception as e:
                    print("❌ Erreur POST :", e)
                    cl.send("HTTP/1.1 400 Bad Request\r\nContent-Type: text/html\r\n\r\n")
                    cl.send("<html><body><h3>❌ Erreur</h3><p>Champs manquants ou invalides.</p></body></html>")
                    cl.close()

            else:
                response = "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: {}\r\n\r\n{}".format(len(html_form), html_form)
                cl.send(response)
                cl.close()

        except Exception as e:
            print("❌ Erreur serveur web :", e)
            try:
                cl.close()
            except:
                pass
