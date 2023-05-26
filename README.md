[![CI](https://github.com/thekoma/ilpost-podcast-scraper/actions/workflows/main.yml/badge.svg)](https://github.com/thekoma/ilpost-podcast-scraper/actions/workflows/main.yml)


![image](https://www.ilpost.it/wp-content/themes/ilpost_2018/images/ilpost.svg)scraper

## Description
This webapp scrapes ilpost.it with your credentials and gives you back a json output of the various podcasts.

## Limitations
You need credentials.
It's not an illegal APP I just want to get the podcasts urls in my domotic home.
I give you only the last episode. I don't need the older ones but feel free to PR of you want to implement the function.

## Endpoint parameters
- /ping -> Expect a pong 200
- /status -> Gives you the status of the components (Redis and SeleniumGrid)
- /cookies -> print redis cookies (or create new cookies if expired)
- /podcasts -> gives you the infromation about all the podcasts (cached)
  - Arguiment refresh=True: Set to any value to trigger scrape
- /getall -> scrape everypodcast (don't do that if not needed)
- /podcast/podcast-name -> gives you the podcast (cached)
  - Arguiment refresh=True: Set to any value to trigger scrape

## Needed components
![|100](https://redis.com/wp-content/themes/wpx/assets/images/logo-redis.svg) Redis Cache.

<img src="https://img.icons8.com/?size=512&id=TLI9oiMzpREF&format=png" width="100px" height="100px"> Selenium Grid

### Output Example
```bash
curl http://localhost:5000/podcast/morning
```

```json
{
"episode": "BLAHBLHABLHA.mp3",
"name": "Morning",
"short_name": "morning",
"description": "Comincia la giornata con la rassegna stampa di Francesco Costa.",
"homepage": "https://www.ilpost.it/episodes/podcasts/morning/",
"last_scrape": 123.1679847,
"last_change": 123.1379847,
"logo": "https://www.ilpost.it/wp-content/uploads/2021/05/evening-1.png"
}
```