const mensagensDiv = document.getElementById('mensagens');
const inputPergunta = document.getElementById('input-pergunta');

function adicionarMensagem(texto, tipo) {
    const div = document.createElement('div');
    div.className = `msg ${tipo}`;
    div.innerHTML = texto;
    mensagensDiv.appendChild(div);
    mensagensDiv.scrollTop = mensagensDiv.scrollHeight;
}

function enviarExemplo(btn) {
    inputPergunta.value = btn.textContent;
    enviarPergunta(new Event('submit'));
}

async function enviarPergunta(event) {
    event.preventDefault();
    const pergunta = inputPergunta.value.trim();
    if (!pergunta) return;

    adicionarMensagem(pergunta, 'usuario');
    inputPergunta.value = '';
    adicionarMensagem('<em>Processando...</em>', 'sistema');

    try {
        const resp = await fetch('/api/consulta', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pergunta }),
        });
        const dados = await resp.json();

        mensagensDiv.removeChild(mensagensDiv.lastChild);

        let html = `<div class="resumo">${dados.resumo}</div>`;

        if (dados.estatisticas && Object.keys(dados.estatisticas).length > 0) {
            const statsTexto = Object.entries(dados.estatisticas)
                .map(([k, v]) => `${k}: ${v}`)
                .join(' | ');
            html += `<div class="stats">${statsTexto}</div>`;
        }

        if (dados.fontes && dados.fontes.length > 0) {
            const fontesTexto = dados.fontes.map(f => f.nome).join(', ');
            html += `<div class="fontes">Fontes: ${fontesTexto} | ${dados.tempo_processamento_ms}ms</div>`;
        }

        html += `<div class="fontes">Intencao: ${dados.intencao_detectada} (${(dados.confianca * 100).toFixed(0)}%)</div>`;

        const temGeo = dados.geojson && dados.geojson.features && dados.geojson.features.length > 0;

        if (temGeo) {
            const n = dados.geojson.features.length;
            html += `<div class="mapa-toggle">`;
            html += `<button class="btn-mostrar-mapa btn-mapa-ativo" onclick="toggleMapaResultado(this)" data-visivel="true">`;
            html += `Ocultar do mapa (${n} registros)`;
            html += `</button>`;
            html += `</div>`;
        }

        adicionarMensagem(html, 'sistema');

        if (temGeo) {
            renderizarGeoJSON(dados.geojson);
        }
    } catch (err) {
        mensagensDiv.removeChild(mensagensDiv.lastChild);
        adicionarMensagem(`Erro: ${err.message}`, 'sistema');
    }
}

function toggleMapaResultado(btn) {
    const visivel = btn.getAttribute('data-visivel') === 'true';
    if (visivel) {
        alternarResultados();
        btn.textContent = 'Mostrar no mapa';
        btn.setAttribute('data-visivel', 'false');
        btn.classList.remove('btn-mapa-ativo');
    } else {
        alternarResultados();
        const n = ultimoGeoJSON ? ultimoGeoJSON.features.length : 0;
        btn.textContent = `Ocultar do mapa (${n} registros)`;
        btn.setAttribute('data-visivel', 'true');
        btn.classList.add('btn-mapa-ativo');
    }
}
