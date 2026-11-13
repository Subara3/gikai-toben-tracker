#!/bin/sh
set -e
cd "$(dirname "$0")/../site"
FILES="index.html search.html og.png data.json rel.json.gz"; [ -f status.json ] && FILES="$FILES status.json"
scp -q $FILES sakura-rs:www/
ssh sakura-rs "mkdir -p ~/www/search && chmod 755 ~/www/search"
scp -q search/* sakura-rs:www/search/
ssh sakura-rs "cd ~/www && chmod 644 $FILES search/*"
curl -sf -o /dev/null https://subara3.sakura.ne.jp/data.json && echo "公開OK https://subara3.sakura.ne.jp/"
