[![CI](https://github.com/thekoma/morning/actions/workflows/main.yml/badge.svg)](https://github.com/thekoma/morning/actions/workflows/main.yml)

TODO:
- Check variables at boot
- Check Redis connection


Endpoint parameters:
- /ping -> Expect a pong 200
- /cookies -> print redis cookies (or create new cookies if expired) 
- /morning -> gives you the podcast (cached)
  - force: Set to any value to trigger cookie refresh and podcast scrape
  - newcookies: Set to any value to trigger cookie refresh
  - fresh: Set to any value to trigger scrape

```bash
curl http://morning:5000/morning?force=True
```