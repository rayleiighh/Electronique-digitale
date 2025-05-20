import ujson
import time

CONFIG_FILE = "config.json"

# ✅ Charger la configuration depuis config.json
def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            config = ujson.load(f)
            print("📂 Configuration chargée :", config)
            return config
    except Exception as e:
        print("❌ Erreur de lecture config.json :", e)
        return None

# ✅ Sauvegarder un objet config dans config.json
def save_config(config):
    try:
        with open(CONFIG_FILE, "w") as f:
            ujson.dump(config, f)
            f.flush()
            try:
                import os
                os.sync()
            except:
                pass
        print("💾 Configuration sauvegardée :", config)
        time.sleep(1.5)  # Pause pour s'assurer que la mémoire Flash est prête
    except Exception as e:
        print("❌ Erreur de sauvegarde config.json :", e)

# ✅ Réinitialiser entièrement config.json
def clear_config():
    try:
        with open(CONFIG_FILE, "w") as f:
            f.write("{}")
            print("🧹 config.json réinitialisé")
    except Exception as e:
        print("❌ Erreur lors de l'effacement de config.json :", e)

# ✅ Mettre à jour un seul champ dans config.json (ajout ou remplacement)
def update_field(key, value):
    config = load_config()
    if config is None:
        config = {}
    config[key] = value
    save_config(config)

# ✅ Vérifie que les champs essentiels sont présents et valides
def config_is_valid(required_fields=["ssid", "password", "deviceId", "deviceSecret"]):
    config = load_config()
    if not config:
        return False
    return all(key in config and config[key] for key in required_fields)
