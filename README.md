# MagmaMC Discord Bot

A Discord bot built with Python and discord.py for the MagmaMC Minecraft community.

## Features

- **Ticket system** with categories (Support, Reports, Financial, Bugs), a dropdown panel,
  per-category staff roles, ticket limits, claim button, confirmation on close and
  `.txt` transcripts sent to a log channel.
- **Partnership system** ("Seja Parceiro") with a two-step application form,
  an organized summary embed for staff, and approve / reject / request info / close buttons.
- **Utility commands**: `/ping`, `/perfil`, `/limpar`.
- Persistent buttons and menus that keep working after restarts.

## Requirements

- Python 3.10+
- A Discord bot token ([Developer Portal](https://discord.com/developers/applications))

## Setup

~~~bash
git clone https://github.com/airton-web/magmamc-discord-bot.git
cd magmamc-discord-bot
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
~~~

Copy `.env.example` to `.env` and paste your bot token:

~~~
DISCORD_TOKEN=your_token_here
~~~

Run the bot:

~~~bash
python bot.py
~~~

## Configuration (inside Discord)

1. `/ticket tipo` - set the category and staff role for each ticket type
2. `/ticket config` - set the log channel and the ticket limit per user
3. `/ticket painel` - send the ticket panel to a channel
4. `/parceria config` and `/parceria painel` - set up and send the partnership panel

## Project structure

~~~
bot.py          # bot setup, general commands and ticket system
parceria.py     # partnership system (discord.py Cog)
.env.example    # environment variables template
~~~

## Tech stack

Python, discord.py, python-dotenv