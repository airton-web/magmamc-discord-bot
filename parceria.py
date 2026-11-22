import asyncio
import io
import json
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

CONFIG_FILE = Path("tickets_config.json")

COR = discord.Color.from_rgb(255, 87, 34)  # laranja "magma"
COR_APROVADO = discord.Color.green()
COR_RECUSADO = discord.Color.red()
COR_INFO = discord.Color.gold()

TIPOS_PARCERIA = {
    "youtuber": ("YouTuber", "🎥"),
    "streamer": ("Streamer (Twitch/Kick)", "📡"),
    "criador": ("Criador de conteúdo (TikTok/Instagram)", "📱"),
    "outra": ("Outra parceria", "🤝"),
}

MSG_APROVADA = (
    "🎉 {dono}, sua solicitação de parceria foi **aprovada** por {equipe}! "
    "Nossa equipe entrará em contato por aqui com os próximos passos."
)
MSG_RECUSADA = (
    "{dono}, agradecemos o interesse no MagmaMC! No momento, sua solicitação de parceria "
    "**não foi aprovada** ({equipe}). Você poderá enviar uma nova proposta no futuro."
)


# ---------- Funções auxiliares ----------
def carregar_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {}


def salvar_config(dados: dict) -> None:
    CONFIG_FILE.write_text(json.dumps(dados, indent=4), encoding="utf-8")


def config_parceria(guild_id: int) -> dict | None:
    cfg = carregar_config().get(str(guild_id), {})
    return cfg.get("tipos", {}).get("parceiro")


def dono_do_ticket(canal) -> int | None:
    topico = getattr(canal, "topic", None)
    if topico and "|" in topico:
        dono = topico.partition("|")[0]
        if dono.isdigit():
            return int(dono)
    return None


def ticket_parceria_aberto(guild: discord.Guild, user_id: int) -> discord.TextChannel | None:
    for canal in guild.text_channels:
        if canal.topic == f"{user_id}|parceiro":
            return canal
    return None


def eh_equipe(membro: discord.Member) -> bool:
    if membro.guild_permissions.administrator:
        return True
    dados = config_parceria(membro.guild.id)
    return bool(dados) and any(r.id == dados["cargo"] for r in membro.roles)


async def checar_equipe(interaction: discord.Interaction) -> bool:
    if eh_equipe(interaction.user):
        return True
    await interaction.response.send_message("Só a equipe responsável pode usar este botão.", ephemeral=True)
    return False


async def enviar_log(guild: discord.Guild, embed: discord.Embed, arquivo: discord.File | None = None):
    cfg = carregar_config().get(str(guild.id), {})
    if cfg.get("logs"):
        canal = guild.get_channel(cfg["logs"])
        if canal:
            await canal.send(embed=embed, file=arquivo)


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


def montar_resumo(user: discord.Member, tipo: str, d: dict, motivo: str, divulgacao: str) -> discord.Embed:
    nome_tipo, emoji = TIPOS_PARCERIA[tipo]
    embed = discord.Embed(
        title="📋 Nova solicitação de parceria",
        description=f"Candidato: {user.mention}",
        color=COR,
        timestamp=discord.utils.utcnow(),
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="👤 Nome / nome artístico", value=d["nome"], inline=True)
    embed.add_field(name="🎯 Tipo de parceria", value=f"{emoji} {nome_tipo}", inline=True)
    embed.add_field(name="🔗 Link do canal/perfil", value=d["link"], inline=False)
    embed.add_field(name="👥 Seguidores/inscritos", value=d["seguidores"], inline=True)
    embed.add_field(name="👁️ Média de visualizações", value=d["visualizacoes"], inline=True)
    embed.add_field(name="📅 Frequência de conteúdo", value=d["frequencia"], inline=True)
    embed.add_field(name="💬 Motivação da parceria", value=motivo, inline=False)
    embed.add_field(name="📣 Proposta de divulgação", value=divulgacao, inline=False)
    embed.set_footer(text="MagmaMC • Status: ⏳ Em análise")
    return embed


# ---------- Criação do ticket ----------
async def criar_ticket_parceria(interaction: discord.Interaction, tipo: str, d: dict, motivo: str, divulgacao: str):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    user = interaction.user

    dados = config_parceria(guild.id)
    categoria = guild.get_channel(dados["categoria"]) if dados else None
    cargo = guild.get_role(dados["cargo"]) if dados else None
    if categoria is None or cargo is None:
        await interaction.followup.send("O sistema de parcerias não está configurado. Avise um administrador.", ephemeral=True)
        return

    if ticket_parceria_aberto(guild, user.id):
        await interaction.followup.send("Você já tem uma solicitação de parceria aberta.", ephemeral=True)
        return

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(
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
        name=f"parceria-{user.name}",
        category=categoria,
        topic=f"{user.id}|parceiro",  # mesmo formato do sistema de tickets principal
        overwrites=overwrites,
    )

    intro = discord.Embed(
        title="🔥 Solicitação recebida!",
        description=(
            f"Olá, {user.mention}! Recebemos sua solicitação de parceria com o **MagmaMC**.\n\n"
            "Nossa equipe analisará as informações enviadas. A aprovação **não é automática** "
            "e depende da análise da administração. Se precisarmos de algo mais, falaremos por aqui."
        ),
        color=COR,
    )
    intro.set_footer(text="MagmaMC — Sua próxima aventura começa aqui!")
    await canal.send(content=f"{user.mention} {cargo.mention}", embed=intro)
    await canal.send(embed=montar_resumo(user, tipo, d, motivo, divulgacao), view=PainelEquipe())

    await interaction.followup.send(f"✅ Solicitação enviada! Acompanhe em {canal.mention}", ephemeral=True)

    log = discord.Embed(title="Nova solicitação de parceria", color=COR)
    log.add_field(name="Canal", value=canal.mention)
    log.add_field(name="Candidato", value=user.mention)
    log.add_field(name="Tipo", value=" ".join(reversed(TIPOS_PARCERIA[tipo])))
    await enviar_log(guild, log)


# ---------- Formulário (2 etapas) ----------
class FormularioParte2(discord.ui.Modal, title="Parceria MagmaMC (2/2)"):
    motivo = discord.ui.TextInput(
        label="Por que quer ser parceiro do MagmaMC?",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )
    divulgacao = discord.ui.TextInput(
        label="Como pretende divulgar o servidor?",
        style=discord.TextStyle.paragraph,
        placeholder="Vídeos, lives, redes sociais, link nas descrições...",
        max_length=1000,
    )

    def __init__(self, tipo: str, dados: dict):
        super().__init__()
        self.tipo = tipo
        self.dados = dados

    async def on_submit(self, interaction: discord.Interaction):
        await criar_ticket_parceria(interaction, self.tipo, self.dados, self.motivo.value, self.divulgacao.value)


class ContinuarView(discord.ui.View):
    def __init__(self, tipo: str, dados: dict):
        super().__init__(timeout=600)
        self.tipo = tipo
        self.dados = dados

    @discord.ui.button(label="Continuar (etapa 2 de 2)", emoji="➡️", style=discord.ButtonStyle.primary)
    async def continuar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FormularioParte2(self.tipo, self.dados))


class FormularioParte1(discord.ui.Modal, title="Parceria MagmaMC (1/2)"):
    nome = discord.ui.TextInput(label="Nome ou nome artístico", max_length=80)
    link = discord.ui.TextInput(
        label="Link do seu canal ou perfil", placeholder="https://...", max_length=200
    )
    seguidores = discord.ui.TextInput(
        label="Quantos seguidores/inscritos você possui?", placeholder="Ex.: 12.500 inscritos", max_length=50
    )
    visualizacoes = discord.ui.TextInput(
        label="Média de visualizações dos seus conteúdos", placeholder="Ex.: 3.000 por vídeo", max_length=50
    )
    frequencia = discord.ui.TextInput(
        label="Frequência de publicações ou lives",
        placeholder="Ex.: 3 vídeos por semana",
        max_length=100,
    )

    def __init__(self, tipo: str):
        super().__init__()
        self.tipo = tipo

    async def on_submit(self, interaction: discord.Interaction):
        dados = {
            "nome": self.nome.value,
            "link": self.link.value,
            "seguidores": self.seguidores.value,
            "visualizacoes": self.visualizacoes.value,
            "frequencia": self.frequencia.value,
        }
        await interaction.response.send_message(
            "✅ Etapa 1 concluída! Clique abaixo para responder as 2 últimas perguntas.",
            view=ContinuarView(self.tipo, dados),
            ephemeral=True,
        )


class EscolherTipoView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.select(
        placeholder="Escolha o tipo de parceria...",
        options=[
            discord.SelectOption(label=nome, value=chave, emoji=emoji)
            for chave, (nome, emoji) in TIPOS_PARCERIA.items()
        ],
    )
    async def escolher(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.send_modal(FormularioParte1(select.values[0]))


# ---------- Painel público ----------
class PainelParceria(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Preencher formulário", emoji="🤝", style=discord.ButtonStyle.success, custom_id="parceria:iniciar"
    )
    async def iniciar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not config_parceria(interaction.guild.id):
            await interaction.response.send_message("As parcerias ainda não foram configuradas.", ephemeral=True)
            return
        aberto = ticket_parceria_aberto(interaction.guild, interaction.user.id)
        if aberto:
            await interaction.response.send_message(f"Você já tem uma solicitação aberta: {aberto.mention}", ephemeral=True)
            return
        await interaction.response.send_message(
            "**Pergunta 1:** qual tipo de parceria você deseja?", view=EscolherTipoView(), ephemeral=True
        )


# ---------- Botões da equipe ----------
class PedirInfoModal(discord.ui.Modal, title="Solicitar mais informações"):
    pergunta = discord.ui.TextInput(
        label="O que você precisa saber?", style=discord.TextStyle.paragraph, max_length=1000
    )

    def __init__(self, mensagem: discord.Message):
        super().__init__()
        self.mensagem = mensagem

    async def on_submit(self, interaction: discord.Interaction):
        embed = self.mensagem.embeds[0]
        embed.color = COR_INFO
        embed.set_footer(text="MagmaMC • Status: 🕒 Aguardando informações do candidato")
        await self.mensagem.edit(embed=embed)
        dono_id = dono_do_ticket(interaction.channel)
        await interaction.response.send_message(
            f"🕒 <@{dono_id}>, a equipe precisa de mais informações:\n>>> {self.pergunta.value}"
        )


async def decidir(interaction: discord.Interaction, status: str, cor: discord.Color, mensagem: str, titulo_log: str):
    if not await checar_equipe(interaction):
        return
    embed = interaction.message.embeds[0]
    embed.color = cor
    embed.set_footer(text=f"MagmaMC • Status: {status} por {interaction.user.display_name}")
    await interaction.response.edit_message(embed=embed, view=PainelEquipe(finalizado=True))

    dono_id = dono_do_ticket(interaction.channel)
    await interaction.channel.send(mensagem.format(dono=f"<@{dono_id}>", equipe=interaction.user.mention))

    log = discord.Embed(title=titulo_log, color=cor)
    log.add_field(name="Candidato", value=f"<@{dono_id}>")
    log.add_field(name="Decidido por", value=interaction.user.mention)
    log.add_field(name="Canal", value=interaction.channel.mention)
    await enviar_log(interaction.guild, log)


async def encerrar_ticket(interaction: discord.Interaction):
    canal = interaction.channel
    await canal.send("🔒 Este ticket será encerrado em 5 segundos...")

    arquivo = await gerar_transcricao(canal)
    log = discord.Embed(title="Ticket de parceria encerrado", color=discord.Color.red())
    log.add_field(name="Canal", value=canal.name)
    log.add_field(name="Candidato", value=f"<@{dono_do_ticket(canal)}>")
    log.add_field(name="Encerrado por", value=interaction.user.mention)
    await enviar_log(interaction.guild, log, arquivo)

    await asyncio.sleep(5)
    await canal.delete(reason=f"Ticket de parceria encerrado por {interaction.user}")


class ConfirmarEncerrar(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=30)

    @discord.ui.button(label="Sim, encerrar", style=discord.ButtonStyle.danger)
    async def sim(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="🔒 Encerrando...", view=None)
        await encerrar_ticket(interaction)

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def nao(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Cancelado.", view=None)


class PainelEquipe(discord.ui.View):
    def __init__(self, finalizado: bool = False):
        super().__init__(timeout=None)
        if finalizado:  # depois da decisão, só o botão de encerrar continua ativo
            for botao in (self.aprovar, self.recusar, self.pedir_info):
                botao.disabled = True

    @discord.ui.button(label="Aprovar parceria", emoji="✅", style=discord.ButtonStyle.success, custom_id="parceria:aprovar")
    async def aprovar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await decidir(interaction, "✅ Aprovada", COR_APROVADO, MSG_APROVADA, "Parceria aprovada")

    @discord.ui.button(label="Recusar parceria", emoji="❌", style=discord.ButtonStyle.danger, custom_id="parceria:recusar")
    async def recusar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await decidir(interaction, "❌ Recusada", COR_RECUSADO, MSG_RECUSADA, "Parceria recusada")

    @discord.ui.button(
        label="Solicitar mais informações", emoji="🕒", style=discord.ButtonStyle.primary, custom_id="parceria:info"
    )
    async def pedir_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await checar_equipe(interaction):
            return
        await interaction.response.send_modal(PedirInfoModal(interaction.message))

    @discord.ui.button(
        label="Encerrar ticket", emoji="🔒", style=discord.ButtonStyle.secondary, custom_id="parceria:encerrar"
    )
    async def encerrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        eh_dono = interaction.user.id == dono_do_ticket(interaction.channel)
        if not (eh_dono or eh_equipe(interaction.user)):
            await interaction.response.send_message("Só a equipe ou o candidato pode encerrar.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Tem certeza que deseja encerrar este ticket?", view=ConfirmarEncerrar(), ephemeral=True
        )


# ---------- Cog (comandos) ----------
class Parceria(commands.Cog):
    parceria = app_commands.Group(name="parceria", description="Sistema de parcerias", guild_only=True)

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(PainelParceria())  # botões continuam funcionando
        self.bot.add_view(PainelEquipe())    # depois de reiniciar o bot

    @parceria.command(name="config", description="Define a categoria e a equipe responsável pelas parcerias")
    @app_commands.describe(
        categoria="Categoria onde os tickets de parceria serão criados",
        cargo="Cargo da equipe que analisa as parcerias",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def parceria_config(
        self, interaction: discord.Interaction, categoria: discord.CategoryChannel, cargo: discord.Role
    ):
        dados = carregar_config()
        cfg = dados.setdefault(str(interaction.guild.id), {})
        cfg.setdefault("logs", None)
        cfg.setdefault("limite", 1)
        cfg.setdefault("tipos", {})["parceiro"] = {"categoria": categoria.id, "cargo": cargo.id}
        salvar_config(dados)
        await interaction.response.send_message(
            f"✅ Parcerias configuradas! Categoria: **{categoria.name}** | Equipe: {cargo.mention}",
            ephemeral=True,
        )

    @parceria.command(name="painel", description="Envia o painel 'Seja Parceiro' neste canal")
    @app_commands.checks.has_permissions(administrator=True)
    async def parceria_painel(self, interaction: discord.Interaction):
        if not config_parceria(interaction.guild.id):
            await interaction.response.send_message("Use `/parceria config` antes de enviar o painel.", ephemeral=True)
            return

        embed = discord.Embed(
            title="🤝 Seja um Parceiro MagmaMC!",
            description=(
                "Você cria conteúdo sobre Minecraft e gostaria de fazer parte da nossa comunidade como parceiro?\n\n"
                "O MagmaMC está aberto a parcerias com **criadores de conteúdo, streamers e produtores de vídeos**.\n\n"
                "Preencha o formulário abaixo para que nossa equipe possa analisar sua proposta."
            ),
            color=COR,
        )
        embed.add_field(
            name="📋 Requisitos básicos",
            value=(
                "• Produzir conteúdo relacionado a Minecraft.\n"
                "• Possuir um canal ou perfil ativo.\n"
                "• Manter uma postura respeitosa e profissional.\n"
                "• Ter interesse genuíno em divulgar o MagmaMC.\n"
                "• Seguir as regras e diretrizes do servidor.\n"
                "• Manter uma frequência razoável de publicações ou transmissões."
            ),
            inline=False,
        )
        embed.add_field(
            name="✅ Como funciona",
            value=(
                "Após preencher o formulário, nossa equipe analisará sua solicitação.\n"
                "A aprovação não é automática e depende da análise da administração."
            ),
            inline=False,
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_footer(text="MagmaMC — Sua próxima aventura começa aqui!")

        await interaction.channel.send(embed=embed, view=PainelParceria())
        await interaction.response.send_message("Painel enviado! ✅", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Parceria(bot))