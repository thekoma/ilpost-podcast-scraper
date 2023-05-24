[![CI](https://github.com/thekoma/ilpost-podcast-scraper/actions/workflows/main.yml/badge.svg)](https://github.com/thekoma/ilpost-podcast-scraper/actions/workflows/main.yml)

TODO:
- Check variables at boot
- Check Redis connection


Endpoint parameters:
- /ping -> Expect a pong 200
- /cookies -> print redis cookies (or create new cookies if expired)
- /podcast/podcast-name -> gives you the podcast (cached)
  - fresh: Set to any value to trigger scrape

```bash
curl http://localhost:5000/podcasts
```