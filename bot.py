import asyncio
import io
import json
import os
import traceback
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN não encontrado. Confira o arquivo .env.")

intents = discord.Intents.default()
intents.members = True  # usado na Etapa 3 (boas-vindas); exige ativar no portal


class MagmaBot(commands.Bot):
    async def setup_hook(self):
        await self.load_extension("parceria")  # sistema "Seja Parceiro"
        await self.load_extension("embeds")    # construtor de embeds
        self.add_view(PainelTicket())
        self.add_view(FecharTicket())
        self.tree.add_command(ticket)
        synced = await self.tree.sync()
        print(f"{len(synced)} comando(s) sincronizado(s)")


bot = MagmaBot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"Bot online como {bot.user}")


# ---------- Tratamento de erros (vale para todos os comandos) ----------
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "Você não tem permissão para usar este comando."
    elif isinstance(error, app_commands.BotMissingPermissions):
        perms = ", ".join(error.missing_permissions)
        msg = f"Eu preciso destas permissões neste canal: **{perms}**."
    else:
        msg = "Algo deu errado ao executar o comando. 😕"
        traceback.print_exception(error)

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


# ---------- Comandos gerais ----------
@bot.tree.command(name="ping", description="Testa se o bot está vivo")
async def ping(interaction: discord.Interaction):
    ms = round(bot.latency * 1000)
    await interaction.response.send_message(f"Pong! 🏓 {ms}ms")


@bot.tree.command(name="perfil", description="Mostra informações de um membro")
@app_commands.describe(membro="Membro que você quer ver")
@app_commands.guild_only()
async def perfil(interaction: discord.Interaction, membro: discord.Member):
    embed = discord.Embed(title=f"Perfil de {membro.display_name}", color=discord.Color.orange())
    embed.set_thumbnail(url=membro.display_avatar.url)
    if membro.joined_at:
        embed.add_field(name="Entrou no servidor", value=discord.utils.format_dt(membro.joined_at, "D"))
    embed.add_field(name="Conta criada", value=discord.utils.format_dt(membro.created_at, "D"))
    embed.set_footer(text=f"ID: {membro.id}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="limpar", description="Apaga mensagens do canal")
@app_commands.describe(quantidade="Quantas mensagens apagar (1 a 100, padrão 100)")
@app_commands.guild_only()
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
async def limpar(interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 100] = 100):
    await interaction.response.defer(ephemeral=True)
    apagadas = await interaction.channel.purge(limit=quantidade)
    await interaction.followup.send(f"🧹 {len(apagadas)} mensagem(ns) apagada(s).", ephemeral=True)


# =====================================================================
#                          SISTEMA DE TICKETS
# =====================================================================
CONFIG_FILE = Path("tickets_config.json")

# "Seja parceiro" tem painel próprio no arquivo parceria.py
TIPOS = {
    "suporte": {
        "nome": "Suporte", "emoji": "🛠️",
        "descricao": "Dúvidas, ajuda geral e problemas na sua conta",
        "cor": discord.Color.blue(),
        "instrucoes": "Conte o que está acontecendo e informe seu nick no jogo. Se tiver prints, envie aqui no ticket.",
        "placeholder": "Ex.: Meu nick é Steve123 e não consigo entrar no servidor desde ontem...",
    },
    "denuncia": {
        "nome": "Denúncias", "emoji": "🚨",
        "descricao": "Denuncie jogadores ou situações que quebram as regras",
        "cor": discord.Color.red(),
        "instrucoes": "Informe o nick do denunciado, o que aconteceu, a data e o horário aproximado. Envie prints ou vídeos como prova. Sua denúncia será analisada com discrição.",
        "placeholder": "Nick do denunciado, o que aconteceu, data/horário e onde ocorreu...",
    },
    "financeiro": {
        "nome": "Financeiro", "emoji": "💰",
        "descricao": "Compras, pagamentos, VIP e reembolsos",
        "cor": discord.Color.gold(),
        "instrucoes": "Informe seu nick, o produto e o comprovante ou ID do pedido. **Nunca envie senhas ou dados de cartão.**",
        "placeholder": "Ex.: Comprei o VIP hoje e não recebi. Nick: Steve123, ID do pedido: ...",
    },
    "bugs": {
        "nome": "Bugs", "emoji": "🐛",
        "descricao": "Reporte erros e falhas do servidor",
        "cor": discord.Color.orange(),
        "instrucoes": "Descreva o que aconteceu, como repetir o erro (passo a passo) e, se possível, envie prints ou vídeo.",
        "placeholder": "O que aconteceu? Como repetir o erro? Em qual modo/mundo foi?",
    },
}
TIPO_CHOICES = [app_commands.Choice(name=i["nome"], value=k) for k, i in TIPOS.items()]


# ---------- Configuração (arquivo JSON) ----------
def carregar_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def salvar_config(dados: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(dados, indent=4), encoding="utf-8")


def config_do_servidor(guild_id: int) -> dict | None:
    return carregar_config().get(str(guild_id))


# ---------- Funções auxiliares ----------
# O tópico do canal guarda "ID_do_dono|tipo", assim sabemos de quem é cada ticket.
def dono_do_ticket(canal) -> int | None:
    topico = getattr(canal, "topic", None)
    if topico and "|" in topico:
        dono = topico.partition("|")[0]
        if dono.isdigit():
            return int(dono)
    return None


def tipo_do_ticket(canal) -> str | None:
    if dono_do_ticket(canal) is None:
        return None
    return canal.topic.partition("|")[2]


def tickets_do_usuario(guild: discord.Guild, user_id: int) -> list[discord.TextChannel]:
    return [c for c in guild.text_channels if dono_do_ticket(c) == user_id]


def cargo_do_ticket(guild: discord.Guild, canal) -> discord.Role | None:
    config = config_do_servidor(guild.id)
    tipo = tipo_do_ticket(canal)
    if not config or tipo not in config.get("tipos", {}):
        return None
    return guild.get_role(config["tipos"][tipo]["cargo"])


def eh_equipe(membro: discord.Member, canal) -> bool:
    cargo = cargo_do_ticket(membro.guild, canal)
    return membro.guild_permissions.administrator or (cargo is not None and cargo in membro.roles)


async def enviar_log(guild: discord.Guild, embed: discord.Embed, arquivo: discord.File | None = None):
    config = config_do_servidor(guild.id)
    if not config or not config.get("logs"):
        return
    canal_log = guild.get_channel(config["logs"])
    if canal_log:
        await canal_log.send(embed=embed, file=arquivo)


async def gerar_transcricao(canal: discord.TextChannel) -> discord.File:
    linhas = []
    async for msg in canal.history(limit=None, oldest_first=True):
        hora = msg.created_at.strftime("%d/%m/%Y %H:%M")
        conteudo = msg.content or ("[embed]" if msg.embeds else "")
        if msg.attachments:
            conteudo += " " + " ".join(a.url for a in msg.attachments)
        linhas.append(f"[{hora}] {msg.author}: {conteudo}")
    dados = io.BytesIO("\n".join(linhas).encode("utf-8"))
    return discord.File(dados, filename=f"transcricao-{canal.name}.txt")


# ---------- Criar ticket ----------
async def criar_ticket(interaction: discord.Interaction, tipo: str, motivo: str):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    info = TIPOS[tipo]

    config = config_do_servidor(guild.id) or {}
    dados_tipo = config.get("tipos", {}).get(tipo)
    categoria = guild.get_channel(dados_tipo["categoria"]) if dados_tipo else None
    cargo = guild.get_role(dados_tipo["cargo"]) if dados_tipo else None
    if categoria is None or cargo is None:
        await interaction.followup.send("Este tipo de ticket não está configurado. Avise um administrador.", ephemeral=True)
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True
        ),
        cargo: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True, attach_files=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, manage_channels=True, read_message_history=True
        ),
    }
    canal = await guild.create_text_channel(
        name=f"{tipo}-{interaction.user.name}",
        category=categoria,
        topic=f"{interaction.user.id}|{tipo}",
        overwrites=overwrites,
    )

    embed = discord.Embed(
        title=f"{info['emoji']} Ticket de {info['nome']}",
        description=(
            f"Olá, {interaction.user.mention}! Obrigado por entrar em contato.\n"
            "A equipe já foi avisada e responderá por aqui assim que possível.\n\n"
            f"📌 **Como agilizar seu atendimento**\n{info['instrucoes']}"
        ),
        color=info["cor"],
    )
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="📝 Seu relato", value=motivo, inline=False)
    embed.set_footer(text="MagmaMC • Use os botões abaixo para assumir ou fechar o ticket")
    await canal.send(content=f"{interaction.user.mention} {cargo.mention}", embed=embed, view=FecharTicket())
    await interaction.followup.send(f"Seu ticket foi criado: {canal.mention}", ephemeral=True)

    log = discord.Embed(title="Ticket aberto", color=discord.Color.green())
    log.add_field(name="Canal", value=canal.mention)
    log.add_field(name="Tipo", value=f"{info['emoji']} {info['nome']}")
    log.add_field(name="Aberto por", value=interaction.user.mention)
    await enviar_log(guild, log)


# ---------- Fechar ticket ----------
async def fechar_ticket(interaction: discord.Interaction):
    canal = interaction.channel
    guild = interaction.guild
    tipo = tipo_do_ticket(canal)
    dono_id = dono_do_ticket(canal)

    await canal.send("🔒 Este ticket será fechado em 5 segundos...")

    arquivo = await gerar_transcricao(canal)
    info = TIPOS.get(tipo, {"nome": tipo or "?", "emoji": "🎫"})
    log = discord.Embed(title="Ticket fechado", color=discord.Color.red())
    log.add_field(name="Canal", value=canal.name)
    log.add_field(name="Tipo", value=f"{info['emoji']} {info['nome']}")
    log.add_field(name="Dono", value=f"<@{dono_id}>")
    log.add_field(name="Fechado por", value=interaction.user.mention)
    await enviar_log(guild, log, arquivo)

    await asyncio.sleep(5)
    await canal.delete(reason=f"Ticket fechado por {interaction.user}")


class ConfirmarFechamento(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(label="Sim, fechar", style=discord.ButtonStyle.danger)
    async def sim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="🔒 Fechando...", view=None)
        await fechar_ticket(interaction)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def nao(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Fechamento cancelado.", view=None)


class FecharTicket(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Assumir", emoji="🙋", style=discord.ButtonStyle.success, custom_id="ticket:assumir")
    async def assumir(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not eh_equipe(interaction.user, interaction.channel):
            await interaction.response.send_message("Só a equipe pode assumir o ticket.", ephemeral=True)
            return

        nova = FecharTicket()
        nova.assumir.disabled = True
        nova.assumir.label = "Assumido"
        await interaction.response.edit_message(view=nova)
        await interaction.channel.send(f"🙋 {interaction.user.mention} assumiu este ticket.")

    @discord.ui.button(label="Fechar", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="ticket:fechar")
    async def fechar(self, interaction: discord.Interaction, button: discord.ui.Button):
        eh_dono = interaction.user.id == dono_do_ticket(interaction.channel)
        if not (eh_dono or eh_equipe(interaction.user, interaction.channel)):
            await interaction.response.send_message("Só o dono do ticket ou a equipe pode fechá-lo.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Tem certeza que deseja fechar este ticket?", view=ConfirmarFechamento(), ephemeral=True
        )


# ---------- Painel (menu de seleção) ----------
class TicketModal(discord.ui.Modal):
    def __init__(self, tipo: str):
        info = TIPOS[tipo]
        super().__init__(title=f"{info['emoji']} {info['nome']}")
        self.tipo = tipo
        self.motivo = discord.ui.TextInput(
            label="Conte-nos o que aconteceu",
            style=discord.TextStyle.paragraph,
            placeholder=info["placeholder"],
            max_length=1000,
        )
        self.add_item(self.motivo)

    async def on_submit(self, interaction: discord.Interaction):
        await criar_ticket(interaction, self.tipo, self.motivo.value)


class SelectTipo(discord.ui.Select):
    def __init__(self):
        opcoes = [
            discord.SelectOption(label=i["nome"], value=k, description=i["descricao"][:100], emoji=i["emoji"])
            for k, i in TIPOS.items()
        ]
        super().__init__(placeholder="📩 Selecione o motivo do seu contato...", options=opcoes, custom_id="ticket:select")

    async def callback(self, interaction: discord.Interaction):
        tipo = self.values[0]
        config = config_do_servidor(interaction.guild.id) or {}

        if tipo not in config.get("tipos", {}):
            await interaction.response.send_message("Este tipo de ticket ainda não foi configurado.", ephemeral=True)
        else:
            abertos = tickets_do_usuario(interaction.guild, interaction.user.id)
            if len(abertos) >= config.get("limite", 1):
                lista = ", ".join(c.mention for c in abertos)
                await interaction.response.send_message(
                    f"Você já atingiu o limite de tickets abertos: {lista}", ephemeral=True
                )
            else:
                await interaction.response.send_modal(TicketModal(tipo))

        # Recria o painel para o menu voltar ao estado inicial (sem opção marcada)
        await interaction.message.edit(view=PainelTicket())


class PainelTicket(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SelectTipo())


# ---------- Comandos de administração ----------
ticket = app_commands.Group(name="ticket", description="Sistema de tickets", guild_only=True)


@ticket.command(name="tipo", description="Configura a categoria e a equipe de um tipo de ticket")
@app_commands.describe(
    tipo="Tipo de ticket",
    categoria="Categoria do Discord onde esse tipo de ticket será criado",
    cargo="Cargo da equipe que atende esse tipo",
)
@app_commands.choices(tipo=TIPO_CHOICES)
@app_commands.checks.has_permissions(administrator=True)
async def ticket_tipo(
    interaction: discord.Interaction,
    tipo: app_commands.Choice[str],
    categoria: discord.CategoryChannel,
    cargo: discord.Role,
):
    dados = carregar_config()
    cfg = dados.setdefault(str(interaction.guild.id), {})
    cfg.setdefault("logs", None)
    cfg.setdefault("limite", 1)
    cfg.setdefault("tipos", {})[tipo.value] = {"categoria": categoria.id, "cargo": cargo.id}
    salvar_config(dados)
    await interaction.response.send_message(
        f"✅ **{tipo.name}** configurado! Categoria: **{categoria.name}** | Equipe: {cargo.mention}",
        ephemeral=True,
    )


@ticket.command(name="config", description="Define o canal de logs e o limite de tickets por pessoa")
@app_commands.describe(
    logs="Canal onde o bot registra tickets abertos e fechados (com transcrição)",
    limite="Máximo de tickets abertos por pessoa (1 a 10)",
)
@app_commands.checks.has_permissions(administrator=True)
async def ticket_config(
    interaction: discord.Interaction,
    logs: discord.TextChannel | None = None,
    limite: int | None = None,
):
    if logs is None and limite is None:
        await interaction.response.send_message("Informe pelo menos o canal de logs ou o limite.", ephemeral=True)
        return
    if limite is not None and not 1 <= limite <= 10:
        await interaction.response.send_message("O limite deve ser entre 1 e 10.", ephemeral=True)
        return

    dados = carregar_config()
    cfg = dados.setdefault(str(interaction.guild.id), {})
    cfg.setdefault("tipos", {})
    cfg.setdefault("logs", None)
    cfg.setdefault("limite", 1)
    if logs is not None:
        cfg["logs"] = logs.id
    if limite is not None:
        cfg["limite"] = limite
    salvar_config(dados)
    await interaction.response.send_message("✅ Configuração salva! Veja tudo com `/ticket status`.", ephemeral=True)


@ticket.command(name="status", description="Mostra a configuração atual dos tickets")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_status(interaction: discord.Interaction):
    cfg = config_do_servidor(interaction.guild.id) or {}
    embed = discord.Embed(title="Configuração dos tickets", color=discord.Color.orange())
    for chave, info in TIPOS.items():
        d = cfg.get("tipos", {}).get(chave)
        valor = f"Categoria: <#{d['categoria']}>\nEquipe: <@&{d['cargo']}>" if d else "❌ Não configurado"
        embed.add_field(name=f"{info['emoji']} {info['nome']}", value=valor, inline=False)

    p = cfg.get("tipos", {}).get("parceiro")
    valor_p = f"Categoria: <#{p['categoria']}>\nEquipe: <@&{p['cargo']}>" if p else "❌ Não configurado (use `/parceria config`)"
    embed.add_field(name="🤝 Seja parceiro", value=valor_p, inline=False)

    logs = cfg.get("logs")
    embed.add_field(name="Canal de logs", value=f"<#{logs}>" if logs else "Não definido")
    embed.add_field(name="Limite por pessoa", value=str(cfg.get("limite", 1)))
    await interaction.response.send_message(embed=embed, ephemeral=True)


@ticket.command(name="painel", description="Envia o painel de tickets neste canal")
@app_commands.describe(titulo="Título do painel", descricao="Texto de apresentação do painel")
@app_commands.checks.has_permissions(administrator=True)
async def ticket_painel(
    interaction: discord.Interaction,
    titulo: str = "🎫 Central de Atendimento MagmaMC",
    descricao: str = (
        "Precisa de ajuda, quer fazer uma denúncia ou reportar um problema?\n"
        "Escolha uma categoria no menu abaixo e nossa equipe vai te atender."
    ),
):
    tipos_config = (config_do_servidor(interaction.guild.id) or {}).get("tipos", {})
    if not any(t in tipos_config for t in TIPOS):
        await interaction.response.send_message("Configure ao menos um tipo com `/ticket tipo` antes.", ephemeral=True)
        return

    categorias = "\n".join(f"{i['emoji']} **{i['nome']}** — {i['descricao']}" for i in TIPOS.values())

    embed = discord.Embed(title=titulo, description=descricao, color=discord.Color.from_rgb(255, 87, 34))
    embed.add_field(name="📂 Categorias de atendimento", value=categorias, inline=False)
    embed.add_field(
        name="📌 Antes de abrir um ticket",
        value=(
            "• Escolha a categoria certa, isso agiliza o seu atendimento.\n"
            "• Descreva o problema com detalhes e envie provas (prints ou vídeos).\n"
            "• Abra um ticket por assunto e mantenha o respeito com a equipe.\n"
            "• **Nunca compartilhe senhas ou dados de cartão.**"
        ),
        inline=False,
    )
    embed.add_field(
        name="⏱️ Atendimento",
        value="Respondemos por ordem de chegada. Evite marcar a equipe, ela já será avisada automaticamente.",
        inline=False,
    )
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    embed.set_footer(text="MagmaMC — Sua próxima aventura começa aqui!")

    await interaction.channel.send(embed=embed, view=PainelTicket())
    await interaction.response.send_message("Painel enviado! ✅", ephemeral=True)


# ---------- Comandos usados dentro do ticket (equipe) ----------
async def checar_equipe_no_ticket(interaction: discord.Interaction) -> bool:
    if tipo_do_ticket(interaction.channel) is None:
        await interaction.response.send_message("Use este comando dentro de um ticket.", ephemeral=True)
        return False
    if not eh_equipe(interaction.user, interaction.channel):
        await interaction.response.send_message("Só a equipe deste ticket pode usar este comando.", ephemeral=True)
        return False
    return True


@ticket.command(name="adicionar", description="Adiciona um membro ao ticket atual")
@app_commands.describe(membro="Membro que vai participar do ticket")
async def ticket_adicionar(interaction: discord.Interaction, membro: discord.Member):
    if not await checar_equipe_no_ticket(interaction):
        return
    await interaction.channel.set_permissions(
        membro, view_channel=True, send_messages=True, read_message_history=True, attach_files=True
    )
    await interaction.response.send_message(f"➕ {membro.mention} foi adicionado ao ticket.")


@ticket.command(name="remover", description="Remove um membro do ticket atual")
@app_commands.describe(membro="Membro que será removido do ticket")
async def ticket_remover(interaction: discord.Interaction, membro: discord.Member):
    if not await checar_equipe_no_ticket(interaction):
        return
    if membro.id == dono_do_ticket(interaction.channel):
        await interaction.response.send_message("Não dá para remover o dono do ticket.", ephemeral=True)
        return
    await interaction.channel.set_permissions(membro, overwrite=None)
    await interaction.response.send_message(f"➖ {membro.mention} foi removido do ticket.")


bot.run(TOKEN)