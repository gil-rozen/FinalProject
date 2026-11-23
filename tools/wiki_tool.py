import requests

class WikipediaTool:
    API_URL = "https://en.wikipedia.org/w/api.php"
    HEADERS = {"User-Agent": "AutonomousGameHarness/1.0 (Local AI Research Agent)"}

    @classmethod
    def fetch_game_context(cls, query: str) -> str:
        # Search specifically for video game, arcade, or classic board game articles
        search_params = {
            "action": "query",
            "list": "search",
            "srsearch": f"{query} video game arcade game",
            "format": "json",
            "srlimit": 5
        }
        try:
            res = requests.get(cls.API_URL, params=search_params, headers=cls.HEADERS, timeout=8)
            res.raise_for_status()
            search_results = res.json().get("query", {}).get("search", [])

            if not search_results:
                return f"No Wikipedia articles found for '{query}'."

            # Select the most relevant title, avoiding physical drinking/party games, songs, films
            disallowed_keywords = ["drinking game", "party game", "album", "film", "soundtrack", "song"]
            best_title = None

            # First pass: look for exact match or '(video game)'
            for item in search_results:
                t = item["title"]
                t_lower = t.lower()
                if any(k in t_lower for k in disallowed_keywords):
                    continue
                if t_lower == query.lower() or f"{query.lower()} (video game)" in t_lower:
                    best_title = t
                    break

            # Second pass: pick the first non-disallowed result
            if not best_title:
                for item in search_results:
                    t = item["title"]
                    if not any(k in t.lower() for k in disallowed_keywords):
                        best_title = t
                        break

            if not best_title:
                best_title = search_results[0]["title"]

            extract_params = {
                "action": "query",
                "prop": "extracts",
                "explaintext": True,
                "titles": best_title,
                "format": "json",
                "exchars": 4000
            }
            ext_res = requests.get(cls.API_URL, params=extract_params, headers=cls.HEADERS, timeout=8)
            ext_res.raise_for_status()
            pages = ext_res.json().get("query", {}).get("pages", {})

            for _, page_data in pages.items():
                extract = page_data.get("extract", "")
                if extract:
                    return f"Source Article: {best_title}\n\n{extract}"

            return f"Could not extract article text for '{best_title}'."
        except Exception as e:
            return f"Wikipedia Search Notice: Offline or unavailable ({str(e)}). Proceed using standard game design knowledge."
