"""motoauction.online, the main source: lots, lot pages with the inspection sheet, and the sales archive."""
import http.cookiejar
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from ..config import UA

SITE = "https://motoauction.online"


class Site:
    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.token = None
        self.token_until = 0

    def _get(self, path, params=None, auth=True):
        url = SITE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"User-Agent": UA, "Accept": "application/json", "Referer": SITE + "/"}
        for attempt in range(3):
            if auth:
                headers["X-Request-Token"] = self._ensure_token()
            try:
                with self.opener.open(urllib.request.Request(url, headers=headers), timeout=30) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                # the site's nginx answers 429 to bursts: wait and retry
                if e.code == 429 and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                # the token can expire before its ttl, e.g. on a long pass: get a new one
                if e.code == 403 and auth and attempt < 2:
                    self.token = None
                    continue
                raise

    def _ensure_token(self):
        if not self.token or time.time() > self.token_until:
            d = self._get("/api/init", auth=False)
            self.token = d["t"]
            self.token_until = time.time() + d.get("ttl", 300) - 30
        return self.token

    def model_groups(self, brand):
        d = self._get("/api/models", {"brand": brand})
        return [m["name"] for m in d.get("models", []) if m.get("name")]

    def lots(self, brand, model, statistics=False):
        """statistics=True returns the archive of past auctions (the site's "Statistics" page)."""
        out, offset = [], 0
        while True:
            params = {"limit": 100, "offset": offset, "brand": brand, "model": model, "skip_count": 1}
            if statistics:
                params["statistics"] = 1
            d = self._get("/api/lots", params)
            page = list((d.get("lots") or {}).values())
            out.extend(page)
            # The site caps a page below the limit asked for (50 since 28.10), so a short page is
            # not the end: follow has_more, and without it stop only at an empty page
            if not page or d.get("has_more") is False:
                return out
            offset += len(page)

    def lot(self, lot_id):
        return self._get(f"/api/lot/{lot_id}")
