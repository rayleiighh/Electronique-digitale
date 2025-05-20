# ========================= IMPORTS =============================
import network, time, machine, utime, math
import urequests as requests
from machine import ADC, Pin, Timer
from config_manager import load_config, clear_config, update_field, config_is_valid
from wifi_setup import start_ap, start_webserver
import ntptime


# code du file main_PROD-v2_PROTOTYPE.py


# ========= Afficheurs 7 segments (2 digits multiplexés) =========
# Broches BCD (LSB → MSB)
BCD = [
    Pin(21, Pin.OUT),  # DB0
    Pin(20, Pin.OUT),  # DB1
    Pin(19, Pin.OUT),  # DB2
    Pin(18, Pin.OUT)   # DB3
]
# Transistors NPN pour activer chaque digit (cathodes communes)
DIZ = Pin(15, Pin.OUT)  # digit dizaines
UNI = Pin(14, Pin.OUT)  # digit unités

# Variables internes au multiplexage
_phase = 0        # 0 ⇒ dizaines, 1 ⇒ unités
unit_digit = 0    # valeur affichée sur le digit unités

def _set_bcd(val: int):
    """Écrit la valeur 0–15 sur les broches BCD."""
    val &= 0x0F
    for bit, pin in enumerate(BCD):
        pin.value((val >> bit) & 1)

def _mux(timer):
    """Callback exécuté à 1 kHz : alterne les deux digits."""
    global _phase
    if _phase == 0:
        DIZ.value(1)    # activer dizaine (toujours 0)
        UNI.value(0)    # désactiver unité
        _set_bcd(0)
    else:
        DIZ.value(0)    # désactiver dizaine
        UNI.value(1)    # activer unité
        _set_bcd(unit_digit)
    _phase ^= 1

# Lancement du multiplexage : 1 kHz
Timer(-1).init(freq=1000, mode=Timer.PERIODIC, callback=_mux)

# ========================= CONSTANTES ==========================
BACKEND_URL = "https://dev-web-2024.onrender.com"
TIMEZONE_OFFSET = 2 * 3600    # décalage en secondes (ex : +2h)

# ========= GPIO & Capteurs (prises + courant) ==================
print("🔄 Démarrage init capteurs et GPIO...")
adc = ADC(Pin(26))
conversion_factor = 3.3 / 65535
# Mapping des prises (GPIO 0-3)
GPIO_MAPPING = {i: Pin(i, Pin.OUT) for i in range(4)}   # GPIO0‑3 → 4 prises
# LEDs pour chaque prise : prise 1 → GPIO13, prise 2 → GPIO12, prise 3 → GPIO11
LED_PINS = {
    0: Pin(13, Pin.OUT),  # LED prise 1
    1: Pin(12, Pin.OUT),  # LED prise 2
    2: Pin(11, Pin.OUT)   # LED prise 3
}
print(f"🔌 GPIO mapping : {list(GPIO_MAPPING.keys())}")
print(f"💡 LED mapping  : {list(LED_PINS.keys())}")

def init_gpio():
    print("🔌 Mise à OFF de toutes les prises et LEDs...")
    # Initialisation sorties prises
    for pin in GPIO_MAPPING.values():
        pin.value(1)  # relais actif LOW -> OFF = HIGH
    # Initialisation LEDs
    for led in LED_PINS.values():
        led.value(0)
    print("🔌 GPIO et LEDs initialisés.")

def calibrer_offset(adc, num_samples=500):
    """Mesure l'offset DC moyen lorsque le capteur n'est pas parcouru par du courant."""
    s = 0
    for _ in range(num_samples):
        s += adc.read_u16() >> 4
        time.sleep_us(500)
    return s // num_samples

# Calibrage au démarrage
offset = calibrer_offset(adc)

# Fonction de mesure du courant RMS
def mesure_courant():
    """Mesure le courant AC RMS, avec offset calibré."""
    CT_RATIO = 1000         # rapport primaire/secondaire du SCT-013-000
    BURDEN   = 100.0        # Ω de la résistance de charge
    volts_per_count = 3.3/4095
    amps_per_count  = (volts_per_count/BURDEN) * CT_RATIO

    num_samples, sum_sq = 500, 0
    for _ in range(num_samples):
        raw = adc.read_u16() >> 4
        diff = raw - offset
        sum_sq += diff * diff
        time.sleep_us(1000)

    rms_counts = math.sqrt(sum_sq / num_samples)
    Irms = rms_counts * amps_per_count
    overload = (Irms > 80.0)
    print(f"📏 Fin mesure → {Irms:.3f} A RMS (surcharge={'OUI' if overload else 'NON'})")
    return Irms, overload

# ========= Connexion Wi‑Fi =====================================
def connecter_wifi(ssid, password, timeout=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(ssid, password)
    print("📶 Connexion à Wi‑Fi :", ssid)
    for i in range(timeout):
        if wlan.isconnected():
            print("✅ IP :", wlan.ifconfig()[0])
            return True
        print("⏳ Tentative", i+1)
        time.sleep(6)
    print("❌ Échec Wi‑Fi")
    return False

# ========= Appairage & Authentification ========================
def appairer_backend(device_id):
    print(f"🔗 Appairage deviceId = {device_id} …")
    try:
        res = requests.post(
            f"{BACKEND_URL}/api/multiprises/link",
            json={"deviceId": device_id},
            headers={"Content-Type": "application/json"}
        )
        print("📥 Appairage HTTP status:", res.status_code)
        if res.status_code == 200:
            device_secret = res.json().get("deviceSecret")
            if device_secret:
                update_field("deviceSecret", device_secret)
                print("🔐 deviceSecret enregistré.")
        res.close()
    except Exception as e:
        print("❌ Erreur appairage :", e)

def recuperer_token(device_id, device_secret):
    try:
        res = requests.post(
            f"{BACKEND_URL}/api/device-auth/login",
            json={"deviceId": device_id, "secret": device_secret},
            headers={"Content-Type": "application/json"}
        )
        print("📥 Auth HTTP status:", res.status_code)
        if res.status_code == 200:
            token = res.json().get("token")
            print("🔑 Token récupéré.")
            return token
        print("❌ Auth failed:", res.text)
    except Exception as e:
        print("❌ Exception auth :", e)
    return None

# ========= Envoi & Sync prises =================================
def envoyer_batch(token, mesures):
    print(f"📤 Envoi batch de {len(mesures)} mesures...")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        res = requests.post(
            f"{BACKEND_URL}/api/consommations/batch",
            json={"measurements": mesures},
            headers=headers
        )
        print("📤 Batch HTTP status:", res.status_code)
        res.close()
    except Exception as e:
        print("❌ Erreur envoi batch :", e)

def mettre_a_jour_prises(token):
    print("🔄 Synchronisation prises…")
    headers = {"Authorization": f"Bearer {token}"}
    try:
        res = requests.get(f"{BACKEND_URL}/api/appareils", headers=headers)
        print("📥 Sync prises HTTP status:", res.status_code)
        appareils = res.json()
        if not isinstance(appareils, list):
            print("❌ Format invalide pour appareils")
            return
        for app in appareils:
            gpio = app.get("gpioIndex")
            etat = app.get("etat", False)
            mode_nuit = app.get("modeNuit", {})
            if mode_nuit.get("actif") and mode_nuit.get("heureDebut") and mode_nuit.get("heureFin"):
                if est_dans_mode_nuit(mode_nuit["heureDebut"], mode_nuit["heureFin"]):
                    etat = False
            if gpio in GPIO_MAPPING:
                # Relais actif LOW -> ON = 0, OFF = 1
                GPIO_MAPPING[gpio].value(0 if etat else 1)
                print(f"⚡ GPIO{gpio} → {'ON' if etat else 'OFF'}")
                # Mise à jour de la LED correspondante si existante
                if gpio in LED_PINS:
                    LED_PINS[gpio].value(1 if etat else 0)
                    print(f"💡 LED prise {gpio} → {'ON' if etat else 'OFF'}")
        res.close()
    except Exception as e:
        print("❌ Erreur sync prises :", e)

# ========= Mode nuit helper ====================================
def est_dans_mode_nuit(heureDebut, heureFin):
    try:
        h_now = utime.localtime()[3] * 60 + utime.localtime()[4]
        h_deb = int(heureDebut[:2]) * 60 + int(heureDebut[3:])
        h_fin = int(heureFin[:2]) * 60 + int(heureFin[3:])
        return (h_deb <= h_fin and h_deb <= h_now < h_fin) or (h_deb > h_fin and (h_now >= h_deb or h_now < h_fin))
    except:
        return False

# ======================= PROGRAMME PRINCIPAL ===================
def main():
    global unit_digit                    # utilisé par le timer afficheur

    print("🚀 Démarrage du programme principal...")
    if not config_is_valid(["ssid", "password", "deviceId"]):
        clear_config(); start_ap(); start_webserver(); machine.reset()

    cfg = load_config()
    if not connecter_wifi(cfg["ssid"], cfg["password"]):
        clear_config(); machine.reset()
    
    # 3) NTP
    try:
        ntptime.settime()
    except:
        pass

    appairer_backend(cfg["deviceId"])
    cfg = load_config()
    token = recuperer_token(cfg["deviceId"], cfg.get("deviceSecret"))
    if not token:
        return

    init_gpio()
    batch, t_start, t_last_update = [], time.time(), 0

    print("✅ Initialisation terminée, entrée dans la boucle principale.")
    while True:
        now = time.time() + TIMEZONE_OFFSET
        print("\n⏱️ Nouvelle itération, timestamp:", now)

        current, _ = mesure_courant()
        batch.append({"timestamp": now, "value": current})
        print(f"📈 Mesure ajoutée: {current:.2f} A")

        # Mise à jour afficheur : nb de prises ON (0-4)
        # Calcul du nombre de prises ON (relais actif LOW → pin.value()==0)
        unit_digit = sum(1 for pin in GPIO_MAPPING.values() if pin.value() == 0)

        if now - t_start >= 10:
            envoyer_batch(token, batch); batch.clear(); t_start = now

        if now - t_last_update >= 5:
            mettre_a_jour_prises(token); t_last_update = now

        time.sleep(3)

# ============================= GO ==============================
main()
