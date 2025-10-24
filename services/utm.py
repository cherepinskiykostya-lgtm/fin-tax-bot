from urllib.parse import urlencode

from settings import settings


def with_utm(url: str) -> str:
    params = {
        "utm_source": settings.UTM_SOURCE,
        "utm_medium": settings.UTM_MEDIUM,
        "utm_campaign": settings.UTM_CAMPAIGN,
    }
    glue = "&" if ("?" in url) else "?"
    return url + glue + urlencode(params)
