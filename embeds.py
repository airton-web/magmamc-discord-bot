import copy
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands

COR_PADRAO = discord.Color.from_rgb(255, 87, 34)  # laranja "magma"

# nome -> hex. O "preto" usa #010101 porque o Discord trata #000000 como "sem cor".
CORES = {
    "laranja": "#FF5722", "vermelho": "#E74C3C", "azul": "#3498DB", "verde": "#2ECC71",
    "roxo": "#9B59B6", "rosa": "#FF69B4", "amarelo": "#F1C40F", "dourado": "#FFD700",
    "ciano": "#1ABC9C", "preto": "#010101", "branco": "#FFFFFF", "cinza": "#95A5A6",
    "blurple": "#5865F2", "invisivel": "#2B2D31",
}
OPCOES_CORES = [  # (chave, emoji, nome exibido)
    ("laranja", "🟠", "Laranja Magma"),
    ("vermelho", "🔴", "Vermelho"),
    ("azul", "🔵", "Azul"),
    ("verde", "🟢", "Verde"),
    ("roxo", "🟣", "Roxo"),
    ("rosa", "💗", "Rosa"),
    ("amarelo", "🟡", "Amarelo"),
    ("dourado", "🏆", "Dourado"),
    ("ciano", "🧊", "Ciano"),
    ("preto", "⚫", "Preto"),
    ("branco", "⚪", "Branco"),
    ("cinza", "🔘", "Cinza"),
    ("blurple", "💠", "Blurple (Discord)"),
    ("invisivel", "🌑", "Invisível (modo escuro)"),
]


# ---------- Funções auxiliares ----------
def converter_cor(texto: str) -> discord.Color | None:
    """Aceita nome (laranja), hex (#FF5722 ou FF5722) e hex curto (#F80)."""
    texto = texto.strip().lower()
    texto = CORES.get(texto, texto).lstrip("#")
    if len(texto) == 3:
        texto = "".join(c * 2 for c in texto)
    if len(texto) != 6 or not all(c in "0123456789abcdef" for c in texto):
        return None
    return discord.Color(int(texto, 16))


def url_valida(texto: str) -> bool:
    return texto.startswith(("http://", "https://")) and " " not in texto


def pode_enviar(interaction: discord.Interaction, canal: discord.abc.GuildChannel) -> str | None:
    """Devolve uma mensagem de erro, ou None se estiver tudo certo."""
    perms_bot = canal.permissions_for(interaction.guild.me)
    if not (perms_bot.view_channel and perms_bot.send_messages and perms_bot.embed_links):
        return f"Eu preciso de **Ver Canal**, **Enviar Mensagens** e **Incorporar Links** em {canal.mention}."
    if not canal.permissions_for(interaction.user).send_messages:
        return f"Você não pode enviar mensagens em {canal.mention}."
    return None


@dataclass
class EstadoEmbed:
    """Guarda tudo que o usuário já configurou e sabe montar o embed final."""
    titulo: str = ""
    descricao: str = ""
    url: str = ""
    cor: discord.Color = field(default_factory=lambda: COR_PADRAO)
    imagem: str = ""
    thumbnail: str = ""
    autor_nome: str = ""
    autor_icone: str = ""
    rodape: str = ""
    rodape_icone: str = ""
    hora: bool = False
    campos: list = field(default_factory=list)  # lista de (nome, valor, lado_a_lado)

    def vazio(self) -> bool:
        return not any([self.titulo, self.descricao, self.imagem, self.thumbnail,
                        self.autor_nome, self.rodape, self.campos])

    def construir(self, preview: bool = False) -> discord.Embed:
        embed = discord.Embed(color=self.cor)
        if self.titulo:
            embed.title = self.titulo
            if self.url:
                embed.url = self.url
        if self.descricao:
            embed.description = self.descricao
        if self.autor_nome:
            embed.set_author(name=self.autor_nome, icon_url=self.autor_icone or None)
        if self.thumbnail:
            embed.set_thumbnail(url=self.thumbnail)
        if self.imagem:
            embed.set_image(url=self.imagem)
        for nome, valor, lado_a_lado in self.campos:
            embed.add_field(name=nome, value=valor, inline=lado_a_lado)
        if self.rodape:
            embed.set_footer(text=self.rodape, icon_url=self.rodape_icone or None)
        if self.hora:
            embed.timestamp = discord.utils.utcnow()
        if preview and self.vazio():
            embed.description = "✨ Seu embed aparecerá aqui. Use os botões abaixo para montar."
        return embed


# ---------- Formulários (modals) ----------
class ModalTexto(discord.ui.Modal, title="Título e descrição"):
    def __init__(self, construtor: "Construtor"):
        super().__init__()
        self.construtor = construtor
        e = construtor.estado
        self.titulo = discord.ui.TextInput(label="Título", default=e.titulo, required=False, max_length=256)
        self.descricao = discord.ui.TextInput(
            label="Descrição (aceita Markdown)", style=discord.TextStyle.paragraph,
            default=e.descricao, required=False, max_length=4000,
        )
        self.url = discord.ui.TextInput(
            label="Link do título (opcional)", default=e.url, required=False,
            placeholder="https://...", max_length=300,
        )
        for item in (self.titulo, self.descricao, self.url):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        url = self.url.value.strip()
        if url and not url_valida(url):
            await interaction.response.send_message("O link do título precisa começar com http:// ou https://", ephemeral=True)
            return

        def alterar(e: EstadoEmbed):
            e.titulo = self.titulo.value.strip()
            e.descricao = self.descricao.value.strip()
            e.url = url

        await self.construtor.aplicar(interaction, alterar)


class ModalCor(discord.ui.Modal, title="Cor personalizada"):
    def __init__(self, construtor: "Construtor"):
        super().__init__()
        self.construtor = construtor
        self.cor = discord.ui.TextInput(
            label="Cor (hex ou nome)", placeholder="Ex.: #FF5722, 00BFFF, laranja, azul...", max_length=20
        )
        self.add_item(self.cor)

    async def on_submit(self, interaction: discord.Interaction):
        cor = converter_cor(self.cor.value)
        if cor is None:
            await interaction.response.send_message(
                "Cor inválida. Use um hex com 6 dígitos (ex.: `#FF5722`) ou um nome. Veja todos com `/embed cores`.",
                ephemeral=True,
            )
            return
        await self.construtor.aplicar(interaction, lambda e: setattr(e, "cor", cor))


class ModalImagens(discord.ui.Modal, title="Imagens"):
    def __init__(self, construtor: "Construtor"):
        super().__init__()
        self.construtor = construtor
        e = construtor.estado
        self.imagem = discord.ui.TextInput(
            label="Imagem grande (URL)", default=e.imagem, required=False,
            placeholder="https://...", max_length=500,
        )
        self.thumbnail = discord.ui.TextInput(
            label="Thumbnail, imagem pequena (URL)", default=e.thumbnail, required=False,
            placeholder="https://...", max_length=500,
        )
        self.add_item(self.imagem)
        self.add_item(self.thumbnail)

    async def on_submit(self, interaction: discord.Interaction):
        imagem, thumbnail = self.imagem.value.strip(), self.thumbnail.value.strip()
        for url in (imagem, thumbnail):
            if url and not url_valida(url):
                await interaction.response.send_message("As URLs precisam começar com http:// ou https://", ephemeral=True)
                return

        def alterar(e: EstadoEmbed):
            e.imagem = imagem
            e.thumbnail = thumbnail

        await self.construtor.aplicar(interaction, alterar)


class ModalAutorRodape(discord.ui.Modal, title="Autor e rodapé"):
    def __init__(self, construtor: "Construtor"):
        super().__init__()
        self.construtor = construtor
        e = construtor.estado
        self.autor = discord.ui.TextInput(
            label="Nome do autor (topo)", default=e.autor_nome, required=False, max_length=256
        )
        self.autor_icone = discord.ui.TextInput(
            label="Ícone do autor (URL)", default=e.autor_icone, required=False,
            placeholder="https://...", max_length=500,
        )
        self.rodape = discord.ui.TextInput(
            label="Texto do rodapé", default=e.rodape, required=False, max_length=500
        )
        self.rodape_icone = discord.ui.TextInput(
            label="Ícone do rodapé (URL)", default=e.rodape_icone, required=False,
            placeholder="https://...", max_length=500,
        )
        for item in (self.autor, self.autor_icone, self.rodape, self.rodape_icone):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        autor, autor_icone = self.autor.value.strip(), self.autor_icone.value.strip()
        rodape, rodape_icone = self.rodape.value.strip(), self.rodape_icone.value.strip()

        if (autor_icone and not autor) or (rodape_icone and not rodape):
            await interaction.response.send_message("Para usar um ícone, preencha também o texto dele.", ephemeral=True)
            return
        for url in (autor_icone, rodape_icone):
            if url and not url_valida(url):
                await interaction.response.send_message("As URLs precisam começar com http:// ou https://", ephemeral=True)
                return

        def alterar(e: EstadoEmbed):
            e.autor_nome, e.autor_icone = autor, autor_icone
            e.rodape, e.rodape_icone = rodape, rodape_icone

        await self.construtor.aplicar(interaction, alterar)


class ModalCampo(discord.ui.Modal, title="Adicionar campo"):
    def __init__(self, construtor: "Construtor"):
        super().__init__()
        self.construtor = construtor
        self.nome = discord.ui.TextInput(label="Nome do campo", max_length=256)
        self.valor = discord.ui.TextInput(
            label="Conteúdo do campo", style=discord.TextStyle.paragraph, max_length=1024
        )
        self.lado = discord.ui.TextInput(
            label="Lado a lado com outros campos? (sim/não)", default="sim", max_length=3
        )
        for item in (self.nome, self.valor, self.lado):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        nome, valor = self.nome.value.strip(), self.valor.value.strip()
        if not nome or not valor:
            await interaction.response.send_message("O campo precisa ter nome e conteúdo.", ephemeral=True)
            return
        lado_a_lado = self.lado.value.strip().lower() in ("sim", "s", "yes", "y")
        await self.construtor.aplicar(interaction, lambda e: e.campos.append((nome, valor, lado_a_lado)))


# ---------- Construtor interativo ----------
class Construtor(discord.ui.View):
    def __init__(self, autor_id: int, canal_id: int):
        super().__init__(timeout=600)
        self.autor_id = autor_id
        self.destino_id = canal_id
        self.estado = EstadoEmbed()
        self.interaction_original: discord.Interaction | None = None

    def texto_status(self) -> str:
        return (
            "🛠️ **Construtor de embed**\n"
            f"📍 Destino: <#{self.destino_id}>\n"
            "Edite pelos botões. A prévia aparece abaixo."
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.autor_id:
            await interaction.response.send_message("Este construtor pertence a outra pessoa.", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        if self.interaction_original:
            try:
                await self.interaction_original.edit_original_response(
                    content="⌛ Construtor expirado. Use `/embed construtor` para começar de novo.",
                    embeds=[], view=None,
                )
            except discord.HTTPException:
                pass

    async def atualizar(self, interaction: discord.Interaction):
        self.btn_hora.label = f"Data/hora: {'ligada' if self.estado.hora else 'desligada'}"
        self.btn_hora.style = discord.ButtonStyle.success if self.estado.hora else discord.ButtonStyle.secondary
        await interaction.response.edit_message(
            content=self.texto_status(), embeds=[self.estado.construir(preview=True)], view=self
        )

    async def aplicar(self, interaction: discord.Interaction, alteracao):
        """Aplica a mudança numa cópia; só confirma se o embed continuar dentro do limite de 6000 caracteres."""
        novo = copy.deepcopy(self.estado)
        alteracao(novo)
        if len(novo.construir()) > 6000 or len(novo.campos) > 25:
            await interaction.response.send_message(
                "⚠️ Essa mudança passaria do limite do Discord (6000 caracteres ou 25 campos). Reduza algum texto.",
                ephemeral=True,
            )
            return
        self.estado = novo
        await self.atualizar(interaction)

    # ----- Linha 0: cores prontas -----
    @discord.ui.select(
        placeholder="🎨 Escolha uma cor pronta...",
        options=[discord.SelectOption(label=nome, value=chave, emoji=emoji) for chave, emoji, nome in OPCOES_CORES],
        row=0,
    )
    async def select_cor(self, interaction: discord.Interaction, select: discord.ui.Select):
        cor = converter_cor(select.values[0])
        await self.aplicar(interaction, lambda e: setattr(e, "cor", cor))

    # ----- Linha 1: textos, cor, imagens, autor -----
    @discord.ui.button(label="Título e texto", emoji="📝", style=discord.ButtonStyle.primary, row=1)
    async def btn_texto(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalTexto(self))

    @discord.ui.button(label="Cor personalizada", emoji="🎨", style=discord.ButtonStyle.secondary, row=1)
    async def btn_cor(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalCor(self))

    @discord.ui.button(label="Imagens", emoji="🖼️", style=discord.ButtonStyle.secondary, row=1)
    async def btn_imagens(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalImagens(self))

    @discord.ui.button(label="Autor e rodapé", emoji="👤", style=discord.ButtonStyle.secondary, row=1)
    async def btn_autor(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalAutorRodape(self))

    # ----- Linha 2: campos, hora, limpar -----
    @discord.ui.button(label="Adicionar campo", emoji="➕", style=discord.ButtonStyle.secondary, row=2)
    async def btn_campo(self, interaction: discord.Interaction, button: discord.ui.Button):
        if len(self.estado.campos) >= 25:
            await interaction.response.send_message("O Discord permite no máximo 25 campos.", ephemeral=True)
            return
        await interaction.response.send_modal(ModalCampo(self))

    @discord.ui.button(label="Remover último campo", emoji="➖", style=discord.ButtonStyle.secondary, row=2)
    async def btn_remover(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.estado.campos:
            await interaction.response.send_message("Não há campos para remover.", ephemeral=True)
            return
        await self.aplicar(interaction, lambda e: e.campos.pop())

    @discord.ui.button(label="Data/hora: desligada", emoji="🕒", style=discord.ButtonStyle.secondary, row=2)
    async def btn_hora(self, interaction: discord.Interaction, button: discord.ui.Button):
        def alternar(e: EstadoEmbed):
            e.hora = not e.hora

        await self.aplicar(interaction, alternar)

    @discord.ui.button(label="Limpar tudo", emoji="🗑️", style=discord.ButtonStyle.danger, row=2)
    async def btn_limpar(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.estado = EstadoEmbed()
        await self.atualizar(interaction)

    # ----- Linha 3: canal de destino -----
    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text, discord.ChannelType.news],
        placeholder="📍 Canal de destino (padrão: o canal atual)",
        row=3,
    )
    async def select_canal(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self.destino_id = select.values[0].id
        await self.atualizar(interaction)

    # ----- Linha 4: enviar / cancelar -----
    @discord.ui.button(label="Enviar", emoji="📤", style=discord.ButtonStyle.success, row=4)
    async def btn_enviar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.estado.vazio():
            await interaction.response.send_message("O embed está vazio. Adicione algum conteúdo primeiro.", ephemeral=True)
            return
        canal = interaction.guild.get_channel(self.destino_id)
        if canal is None:
            await interaction.response.send_message("Não encontrei o canal de destino.", ephemeral=True)
            return
        erro = pode_enviar(interaction, canal)
        if erro:
            await interaction.response.send_message(erro, ephemeral=True)
            return

        await canal.send(embed=self.estado.construir())
        self.stop()
        await interaction.response.edit_message(content=f"✅ Embed enviado em {canal.mention}!", embeds=[], view=None)

    @discord.ui.button(label="Cancelar", emoji="❌", style=discord.ButtonStyle.secondary, row=4)
    async def btn_cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Construtor cancelado.", embeds=[], view=None)


# ---------- Cog (comandos) ----------
class Embeds(commands.Cog):
    grupo = app_commands.Group(
        name="embed",
        description="Criação de embeds personalizados",
        guild_only=True,
        default_permissions=discord.Permissions(manage_messages=True),
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @grupo.command(name="construtor", description="Abre o construtor interativo de embeds, com prévia ao vivo")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_construtor(self, interaction: discord.Interaction):
        view = Construtor(interaction.user.id, interaction.channel.id)
        await interaction.response.send_message(
            content=view.texto_status(),
            embeds=[view.estado.construir(preview=True)],
            view=view,
            ephemeral=True,
        )
        view.interaction_original = interaction

    @grupo.command(name="rapido", description="Cria e envia um embed com um único comando")
    @app_commands.describe(
        titulo="Título do embed",
        descricao="Texto principal (use \\n para quebrar linha)",
        cor="Hex (#FF5722) ou nome (laranja, azul...). Veja /embed cores",
        canal="Canal de destino (padrão: o canal atual)",
        imagem="URL da imagem grande",
        thumbnail="URL da imagem pequena (canto)",
        rodape="Texto do rodapé",
        hora="Mostrar data e hora no rodapé",
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_rapido(
        self,
        interaction: discord.Interaction,
        titulo: str | None = None,
        descricao: str | None = None,
        cor: str = "laranja",
        canal: discord.TextChannel | None = None,
        imagem: str | None = None,
        thumbnail: str | None = None,
        rodape: str | None = None,
        hora: bool = False,
    ):
        estado = EstadoEmbed(
            titulo=(titulo or "").strip(),
            descricao=(descricao or "").replace("\\n", "\n").strip(),
            imagem=(imagem or "").strip(),
            thumbnail=(thumbnail or "").strip(),
            rodape=(rodape or "").strip(),
            hora=hora,
        )

        cor_convertida = converter_cor(cor)
        if cor_convertida is None:
            await interaction.response.send_message("Cor inválida. Veja as opções com `/embed cores`.", ephemeral=True)
            return
        estado.cor = cor_convertida

        if len(estado.titulo) > 256 or len(estado.descricao) > 4096 or len(estado.rodape) > 2048:
            await interaction.response.send_message("Algum texto passou do limite (título 256, descrição 4096, rodapé 2048).", ephemeral=True)
            return
        for url in (estado.imagem, estado.thumbnail):
            if url and not url_valida(url):
                await interaction.response.send_message("As URLs das imagens precisam começar com http:// ou https://", ephemeral=True)
                return
        if estado.vazio():
            await interaction.response.send_message("Informe pelo menos título, descrição, imagem ou rodapé.", ephemeral=True)
            return

        destino = canal or interaction.channel
        erro = pode_enviar(interaction, destino)
        if erro:
            await interaction.response.send_message(erro, ephemeral=True)
            return

        await destino.send(embed=estado.construir())
        await interaction.response.send_message(f"✅ Embed enviado em {destino.mention}!", ephemeral=True)

    @grupo.command(name="cores", description="Mostra as cores prontas e como usar cores personalizadas")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def embed_cores(self, interaction: discord.Interaction):
        linhas = "\n".join(f"{emoji} **{nome}** · `{chave}` · `{CORES[chave]}`" for chave, emoji, nome in OPCOES_CORES)
        embed = discord.Embed(title="🎨 Guia de cores", color=COR_PADRAO)
        embed.add_field(name="Cores prontas (use o nome)", value=linhas, inline=False)
        embed.add_field(
            name="Cor personalizada (use o hex)",
            value=(
                "Código com **6 dígitos**, com ou sem `#`. Exemplos: `#FF5722`, `00BFFF`.\n"
                "Também vale a forma curta de 3 dígitos: `#F80`.\n"
                "Qualquer seletor de cores (color picker) mostra o código hex."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Embeds(bot))