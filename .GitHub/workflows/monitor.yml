name: Switch 2 Zelda Stock Monitor

on:
  schedule:
    - cron: "*/10 * * * *"   # every 10 minutes
  workflow_dispatch: {}       # lets you also trigger it manually from the Actions tab

jobs:
  check-stock:
    runs-on: ubuntu-latest
    steps:
      - name: Check out repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install requests beautifulsoup4

      - name: Run stock check
        env:
          DISCORD_WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK_URL }}
        run: python monitor.py

      - name: Commit updated state
        run: |
          git config --global user.name "stock-monitor-bot"
          git config --global user.email "actions@github.com"
          git add state.json
          git diff --quiet --cached || git commit -m "Update stock state"
          git push
