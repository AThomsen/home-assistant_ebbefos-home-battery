import voluptuous as vol

DOMAIN = "xolta_batt"
UPDATE_INTERVAL_SEC = 60
CONF_BEARER_TOKEN = "bearer_token"

# Validation of the user's configuration
XOLTA_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BEARER_TOKEN): str,
    }
)
