import voluptuous as vol

DOMAIN = "ebbefos_home_battery"
DASHBOARD_UPDATE_INTERVAL_SEC = 60
ENERGY_UPDATE_INTERVAL_SEC = 5 * 60
CONF_BEARER_TOKEN = "bearer_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_TOKEN_EXPIRES_AT = "token_expires_at"

EBBEFOS_OIDC_TOKEN_ENDPOINT = "https://id.ebbefos.dk/connect/token"
EBBEFOS_OIDC_CLIENT_ID = "napp"
EBBEFOS_OIDC_SCOPE = "openid profile email offline_access xeam_profile"

# Validation of the user's configuration
EBBEFOS_CONFIG_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REFRESH_TOKEN): str,
    }
)
