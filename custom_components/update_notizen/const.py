"""Konstanten für Update-Notizen."""

DOMAIN = "update_notizen"

CONF_UHRZEIT = "uhrzeit"
CONF_INTERVALL = "intervall"
CONF_NUR_AENDERUNG = "nur_bei_aenderung"
CONF_MAX_ZEICHEN = "max_zeichen"

STANDARD_OPTIONEN = {
    CONF_UHRZEIT: "10:00:00",
    CONF_INTERVALL: 24,  # Stunden
    CONF_NUR_AENDERUNG: False,
    CONF_MAX_ZEICHEN: 3500,
}

EREIGNIS_BERICHT = "update_notizen_bericht"
DIENST_ABRUFEN = "abrufen"
