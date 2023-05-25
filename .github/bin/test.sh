#!/bin/bash
set -ex
try=0
retry=12
exit_var=1
sleep=5

echo 🐳 Setting up docker composer

cp .env.dist .env
sudo snap install yq
yq -i '.services.ilpostscraper.image=env(TEST_IMAGE)' docker-compose.yml
docker-compose -f docker-compose.yml up -d
set +e
echo "🚦 Starting checks."
while [ $try -lt $retry ]; do
	((try++))
	health=$(docker inspect "$(docker-compose ps -q ilpostscraper)" | jq '.[0] | .State.Health.Status' | sed 's/"//g')
	echo "🔍 Checking...[${try}/${retry}]"
	if [ "${health}" == "healthy" ]; then
		exit_var=0
		break
	else
		docker-compose ps
		docker-compose logs ilpostscraper
		echo "⏳ Not ready. Sleeping $sleep seconds. "
		sleep $sleep
	fi
done

if [ $exit_var == 1 ]; then
	echo "🚨 Test failed"
else
	echo "🌞 The scraper is healthy! Great Job!"
fi

docker-compose down -v -t 1 --remove-orphans
exit $exit_var
