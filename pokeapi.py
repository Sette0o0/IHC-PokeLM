import subprocess
import threading
import json
import telebot
from openai import OpenAI
from rich import print as rprint
import pokebase as pb
from functools import lru_cache
import os
import whisper

# --- 1. CONFIGURAÇÕES INICIAIS ---
TELEGRAM_TOKEN = "8848622707:AAGSIgb9T67WUANsl1K9JrQua-TZGYZzi3c" 
MODEL = "llama3.2" # Llama 3.2 (3B) é bem mais rápido e leve!

# Inicializando o Bot do Telegram
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- 2. OLLAMA (Local LLM) ---
def setup_ollama():
    rprint("[bold yellow]Iniciando o servidor do Ollama...[/bold yellow]")
    
    rprint(f"[bold yellow]Garantindo que o modelo {MODEL} esteja baixado...[/bold yellow]")
    subprocess.run(["ollama", "pull", MODEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rprint("[bold green]Ollama pronto![/bold green]")

thread = threading.Thread(target=setup_ollama, daemon=True)
thread.start()
thread.join() 

ALL_TYPES = [
    "normal", "fire", "water", "electric", "grass", "ice",
    "fighting", "poison", "ground", "flying", "psychic",
    "bug", "rock", "ghost", "dragon", "dark", "steel", "fairy"
]

@lru_cache(maxsize=256)
def _get_pokemon(nome: str):
    try:
        return pb.pokemon(nome.lower())
    except Exception:
        return None

@lru_cache(maxsize=256)
def _get_type(tipo: str):
    try:
        return pb.type_(tipo.lower())
    except Exception:
        return None

def get_pokemon_types(pokemon_name: str) -> dict:
    poke = _get_pokemon(pokemon_name)
    if not poke:
        return {"error": f"Pokémon '{pokemon_name}' não encontrado."}
    return {"pokemon_name": pokemon_name, "types": [t.type.name for t in poke.types]}

def get_pokemons_of_type(pokemon_type: str) -> dict:
    tipo = _get_type(pokemon_type)
    if not tipo:
        return {"error": f"Tipo '{pokemon_type}' não encontrado."}
    return {"type": pokemon_type, "pokemons": [p.pokemon.name for p in tipo.pokemon]}

def get_type_defense(pokemon_type: str) -> dict:
    tipo = _get_type(pokemon_type)
    if not tipo:
        return {"error": f"Tipo '{pokemon_type}' não encontrado."}
    relations = tipo.damage_relations
    return {
        "type": pokemon_type,
        "resistencias": [t.name for t in relations.half_damage_from],
        "fraquezas": [t.name for t in relations.double_damage_from],
        "imunidades": [t.name for t in relations.no_damage_from],
    }

def get_pokemon_defense(pokemon_name: str) -> dict:
    poke = _get_pokemon(pokemon_name)
    if not poke:
        return {"error": f"Pokémon '{pokemon_name}' não encontrado."}

    poke_types = [t.type.name for t in poke.types]
    defense = {t: 1.0 for t in ALL_TYPES}

    for p_type in poke_types:
        tipo = _get_type(p_type)
        if not tipo:
            continue
        relations = tipo.damage_relations
        for t in relations.half_damage_from:
            defense[t.name] *= 0.5
        for t in relations.double_damage_from:
            defense[t.name] *= 2.0
        for t in relations.no_damage_from:
            defense[t.name] = 0.0

    resultado = {"pokemon_name": pokemon_name, "types": poke_types,
                 "muito_fraco": [], "fraco": [], "neutro": [],
                 "resistente": [], "muito_resistente": [], "imune": []}

    for tipo, mult in defense.items():
        if mult == 0:      resultado["imune"].append(tipo)
        elif mult == 0.25: resultado["muito_resistente"].append(tipo)
        elif mult == 0.5:  resultado["resistente"].append(tipo)
        elif mult == 2:    resultado["fraco"].append(tipo)
        elif mult == 4:    resultado["muito_fraco"].append(tipo)
        else:              resultado["neutro"].append(tipo)

    return resultado

def get_pokemon_stats(pokemon_name: str) -> dict:
    poke = _get_pokemon(pokemon_name)
    if not poke:
        return {"error": f"Pokémon '{pokemon_name}' não encontrado."}
    stats = {s.stat.name: s.base_stat for s in poke.stats}
    return {"pokemon_name": pokemon_name, "stats": stats, "total": sum(stats.values())}

def get_pokemon_abilities(pokemon_name: str) -> dict:
    poke = _get_pokemon(pokemon_name)
    if not poke:
        return {"error": f"Pokémon '{pokemon_name}' não encontrado."}
    abilities = []
    for a in poke.abilities:
         abilities.append({
             "name": a.ability.name,
             "is_hidden": a.is_hidden
         })
    return {"pokemon_name": pokemon_name, "abilities": abilities}

def get_pokemon_evolution_chain(pokemon_name: str) -> dict:
    try:
        species = pb.pokemon_species(pokemon_name.lower())
        chain = species.evolution_chain
        
        def extract_chain(link):
            result = [link.species.name]
            for evolves_to in link.evolves_to:
                result.extend(extract_chain(evolves_to))
            return result
        
        evolutions = extract_chain(chain.chain)
        return {"pokemon_name": pokemon_name, "evolution_chain": evolutions}
    except Exception as e:
        return {"error": f"Não foi possível encontrar a linha evolutiva de '{pokemon_name}'."}
def suggest_team_addition(current_team: list) -> dict:
    import random
    team_weaknesses = {t: 0 for t in ALL_TYPES}
    team_resistances = {t: 0 for t in ALL_TYPES}
    
    for poke_name in current_team:
        defense_data = get_pokemon_defense(poke_name)
        if "error" in defense_data:
            return {"error": f"Não foi possível calcular pois o Pokémon '{poke_name}' é inválido."}
        
        for t in defense_data["fraco"] + defense_data["muito_fraco"]:
            team_weaknesses[t] += 1
        for t in defense_data["resistente"] + defense_data["muito_resistente"] + defense_data["imune"]:
            team_resistances[t] += 1
            
    vulnerabilities = {}
    for t in ALL_TYPES:
        net = team_weaknesses[t] - team_resistances[t]
        if net > 0:
            vulnerabilities[t] = net
            
    sorted_vuln = sorted(vulnerabilities.items(), key=lambda x: x[1], reverse=True)
    if not sorted_vuln:
        return {"mensagem": "O time atual já tem uma ótima cobertura defensiva! Nenhuma grande fraqueza."}
        
    maiores_fraquezas = [v[0] for v in sorted_vuln[:3]]
    
    sugestoes_de_tipos = []
    for tipo_str in ALL_TYPES:
        tipo_data = _get_type(tipo_str)
        if not tipo_data:
            continue
            
        resiste_a = [t.name for t in tipo_data.damage_relations.half_damage_from] + \
                    [t.name for t in tipo_data.damage_relations.no_damage_from]
        
        score = sum(1 for w in maiores_fraquezas if w in resiste_a)
        if score > 0:
            sugestoes_de_tipos.append({"tipo": tipo_str, "score": score})
            
    if not sugestoes_de_tipos:
         return {"maiores_fraquezas_do_time": maiores_fraquezas, "mensagem": "Não encontrei um único tipo que resista perfeitamente a tudo isso."}

    sugestoes_de_tipos.sort(key=lambda x: x["score"], reverse=True)
    best_score = sugestoes_de_tipos[0]["score"]
    melhores_tipos = [s["tipo"] for s in sugestoes_de_tipos if s["score"] == best_score]
    
    exemplos = []
    for tipo in melhores_tipos[:3]:
        tipo_data = _get_type(tipo)
        pokemons_desse_tipo = [p.pokemon.name for p in tipo_data.pokemon]
        if pokemons_desse_tipo:
            exemplos.extend(random.sample(pokemons_desse_tipo, min(2, len(pokemons_desse_tipo))))
    
    return {
        "time_atual": current_team,
        "maiores_fraquezas_do_time": maiores_fraquezas,
        "tipos_sugeridos_para_adicionar": melhores_tipos[:3],
        "exemplos_de_pokemon_sugeridos": list(set(exemplos))
    }

TOOLS_MAP = {
    "get_pokemon_types": get_pokemon_types,
    "get_pokemons_of_type": get_pokemons_of_type,
    "get_type_defense": get_type_defense,
    "get_pokemon_defense": get_pokemon_defense,
    "get_pokemon_stats": get_pokemon_stats,
    "get_pokemon_abilities": get_pokemon_abilities,
    "get_pokemon_evolution_chain": get_pokemon_evolution_chain,
    "suggest_team_addition": suggest_team_addition,
}

client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_pokemon_types",
            "description": "Retorna os tipos de um Pokémon (ex: Fire, Flying para Charizard).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_name": {"type": "string", "description": "Nome do Pokémon em minúsculas."}
                },
                "required": ["pokemon_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pokemons_of_type",
            "description": "Lista todos os Pokémon de um determinado tipo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_type": {"type": "string", "description": "Nome do tipo em inglês (ex: fire, water, dragon)."}
                },
                "required": ["pokemon_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_type_defense",
            "description": "Retorna fraquezas, resistências e imunidades de um tipo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_type": {"type": "string", "description": "Nome do tipo (ex: fire, psychic)."}
                },
                "required": ["pokemon_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pokemon_defense",
            "description": "Retorna a tabela defensiva completa de um Pokémon com multiplicadores reais.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_name": {"type": "string", "description": "Nome do Pokémon."}
                },
                "required": ["pokemon_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pokemon_stats",
            "description": "Retorna os stats base de um Pokémon.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_name": {"type": "string", "description": "Nome do Pokémon."}
                },
                "required": ["pokemon_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pokemon_abilities",
            "description": "Retorna as habilidades de um Pokémon, incluindo se são ocultas (hidden abilities).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_name": {"type": "string", "description": "Nome do Pokémon."}
                },
                "required": ["pokemon_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_pokemon_evolution_chain",
            "description": "Retorna a linha evolutiva completa de um Pokémon.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pokemon_name": {"type": "string", "description": "Nome do Pokémon."}
                },
                "required": ["pokemon_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "suggest_team_addition",
            "description": "Analisa as fraquezas de um time de Pokémon fornecido e sugere novos tipos e exemplos de Pokémon para equilibrar o time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_team": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Lista com os nomes dos Pokémon que já estão no time."
                    }
                },
                "required": ["current_team"]
            }
        }
    }
]

SYSTEM_PROMPT = (
    "Você é o Professor Pokémon, um especialista muito gentil e prestativo. "
    "Seu objetivo é ajudar treinadores respondendo a perguntas sobre o mundo Pokémon de forma clara e detalhada. "
    "Sempre use as tools (funções) disponíveis para buscar dados reais antes de responder — nunca invente informações, estatísticas, evoluções ou habilidades. "
    "Responda em português do Brasil, de forma amigável, e utilize a formatação Markdown do Telegram quando for adequado. "
    "Se o usuário fizer perguntas que não sejam sobre Pokémon, responda educadamente que sua especialidade é apenas o universo Pokémon."
    "Não traduza nomes de pokemons, habilidades ou tipos para o português, use os nomes originais em inglês (ex: Charizard, Overgrow, Water)."
)

def executar_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name not in TOOLS_MAP:
        return json.dumps({"error": f"Tool '{tool_name}' não encontrada."})
    try:
        return json.dumps(TOOLS_MAP[tool_name](**tool_input), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})

def chat_com_pokemon(pergunta: str, messages: list) -> tuple[str, list]:
    messages.append({"role": "user", "content": pergunta})

    while True:
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
            )
        except Exception as e:
            return f"Ocorreu um erro ao conectar com o Ollama: {e}", messages

        msg = response.choices[0].message
        messages.append(msg)

        if not msg.tool_calls:
            return msg.content or "(sem resposta do modelo)", messages

        for tool_call in msg.tool_calls:
            nome = tool_call.function.name
            args = json.loads(tool_call.function.arguments)
            rprint(f"[dim] Modelo acionou tool: [bold]{nome}[/bold]({args})[/dim]")

            resultado = executar_tool(nome, args)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": resultado,
            })

# --- 4. WHISPER E LÓGICA DO TELEGRAM ---
historico_por_chat = {}

rprint("[bold yellow]Carregando modelo Whisper (base) para mensagens de voz...[/bold yellow]")
try:
    import warnings
    warnings.filterwarnings("ignore", message=".*FP16.*") # ignora aviso comum no Windows
    whisper_model = whisper.load_model("base")
    rprint("[bold green]Whisper pronto![/bold green]")
except Exception as e:
    rprint(f"[bold red]Aviso: Erro ao carregar Whisper. Verifique se o ffmpeg está instalado. Erro: {e}[/bold red]")
    whisper_model = None

@bot.message_handler(commands=['start', 'help', 'menu'])
def send_welcome(message):
    texto = (
        "Olá! Eu sou o Professor Pokémon! 🌿🔥💧\n\n"
        "Você pode me perguntar sobre tipos, fraquezas, atributos base, habilidades ou até a linha evolutiva de qualquer Pokémon! "
        "Estou aqui para ajudar na sua jornada. Selecione uma opção no menu abaixo ou digite sua pergunta:"
    )
    
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    item1 = telebot.types.KeyboardButton("🔥 Dica para o meu time")
    item2 = telebot.types.KeyboardButton("🧬 Linha evolutiva")
    item3 = telebot.types.KeyboardButton("⚔️ Fraquezas e Vantagens")
    item4 = telebot.types.KeyboardButton("📊 Atributos e Habilidades")
    markup.add(item1, item2, item3, item4)

    bot.reply_to(message, texto, reply_markup=markup)

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    chat_id = message.chat.id
    
    if whisper_model is None:
        bot.reply_to(message, "Desculpe, o reconhecimento de voz não está disponível. Verifique se o FFmpeg e o Whisper estão instalados corretamente no servidor.")
        return
        
    bot.send_chat_action(chat_id, 'typing')
    rprint(f"[cyan]Recebendo áudio de {message.from_user.first_name}...[/cyan]")
    
    try:
        file_info = bot.get_file(message.voice.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        temp_audio_path = f"temp_voice_{chat_id}.ogg"
        with open(temp_audio_path, 'wb') as new_file:
            new_file.write(downloaded_file)
            
        rprint("[yellow]Transcrevendo áudio...[/yellow]")
        result = whisper_model.transcribe(temp_audio_path, language="pt")
        pergunta = result["text"].strip()
        
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)
            
        if not pergunta:
            bot.reply_to(message, "Não consegui escutar nada no áudio. Pode repetir?")
            return
            
        rprint(f"[cyan]Áudio transcrito:[/cyan] {pergunta}")
        
        if chat_id not in historico_por_chat:
            historico_por_chat[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        historico = historico_por_chat[chat_id]
        
        if len(historico) > 20:
            historico = [historico[0]] + historico[-10:]

        resposta, novo_historico = chat_com_pokemon(pergunta, historico)
        historico_por_chat[chat_id] = novo_historico
        
        try:
            bot.reply_to(message, f'🗣️ *Você disse:* "{pergunta}"\n\n' + resposta, parse_mode="Markdown")
        except telebot.apihelper.ApiTelegramException:
            bot.reply_to(message, f'🗣️ Você disse: "{pergunta}"\n\n' + resposta)
            
    except Exception as e:
        rprint(f"[bold red]Erro ao processar áudio:[/bold red] {e}")
        bot.reply_to(message, "Ocorreu um erro ao processar o seu áudio. Tem certeza que o FFmpeg está instalado?")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    pergunta = message.text
    
    rprint(f"[cyan]Recebido de {message.from_user.first_name}:[/cyan] {pergunta}")
    
    # Mostra o status de "Digitando..." no aplicativo do Telegram do usuário
    bot.send_chat_action(chat_id, 'typing')

    if chat_id not in historico_por_chat:
        historico_por_chat[chat_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    historico = historico_por_chat[chat_id]
    
    # Limita o histórico para não exceder a janela de contexto do Llama
    # Mantém o SYSTEM PROMPT no topo e preserva apenas as 10 últimas mensagens
    if len(historico) > 20:
        historico = [historico[0]] + historico[-10:]

    resposta, novo_historico = chat_com_pokemon(pergunta, historico)
    historico_por_chat[chat_id] = novo_historico
    
    try:
        # Tenta enviar com suporte a Markdown
        bot.reply_to(message, resposta, parse_mode="Markdown")
    except telebot.apihelper.ApiTelegramException:
        # Se falhar (ex: caracteres especiais soltos), tenta enviar sem formatação
        bot.reply_to(message, resposta)

if __name__ == "__main__":
    rprint("[bold green]Bot do Telegram iniciado e rodando no Windows![/bold green]")
    rprint("[bold white]Para parar o bot, feche este terminal ou pressione Ctrl+C[/bold white]")
    # Inicia o loop para escutar novas mensagens do Telegram sem parar
    import time
    while True:
        try:
            bot.polling(non_stop=True)
        except Exception as e:
            rprint(f"[bold red]Conexão perdida, tentando reconectar em 5 segundos... Erro: {e}[/bold red]")
            time.sleep(5)
