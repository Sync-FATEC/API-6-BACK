/* Mapa ASG-SP - Satelite + resultados de consulta */

const mapa = L.map('mapa', { zoomControl: true }).setView([-22.5, -48.5], 7);

L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: '&copy; Esri',
    maxZoom: 18,
}).addTo(mapa);

/* Fronteiras + nomes de cidades/estados */
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png', {
    maxZoom: 18,
    opacity: 0.8,
    pane: 'overlayPane',
}).addTo(mapa);

/* Estado */
let camadaResultados = null;
let legendaControl = null;
let resultadosVisiveis = false;
let ultimoGeoJSON = null;

const CORES = {
    queimadas: { cor: '#ff4444', nome: 'Queimadas' },
    deter:     { cor: '#ff8c00', nome: 'Desmatamento' },
    funai:     { cor: '#4488ff', nome: 'Terras Indigenas' },
    icmbio:    { cor: '#22cc66', nome: 'Unidades de Conservacao' },
    palmares:  { cor: '#e056c1', nome: 'Quilombolas' },
    prodes:    { cor: '#cc6600', nome: 'Desmatamento PRODES' },
};
const COR_PADRAO = '#9b59b6';

/* Renderizar GeoJSON dos resultados */
function renderizarGeoJSON(geojson) {
    limparMapa();
    if (!geojson || !geojson.features || geojson.features.length === 0) return;

    ultimoGeoJSON = geojson;
    resultadosVisiveis = true;
    const fontesPresentes = new Set();

    camadaResultados = L.geoJSON(geojson, {
        pointToLayer: function(feature, latlng) {
            const fonte = feature.properties.fonte || '';
            const cfg = CORES[fonte] || {};
            fontesPresentes.add(fonte);
            return L.circleMarker(latlng, {
                radius: 10,
                fillColor: cfg.cor || COR_PADRAO,
                color: '#fff',
                weight: 2,
                fillOpacity: 0.9,
            });
        },
        style: function(feature) {
            const fonte = feature.properties.fonte || '';
            const cfg = CORES[fonte] || {};
            fontesPresentes.add(fonte);
            return {
                color: cfg.cor || COR_PADRAO,
                weight: 3,
                fillColor: cfg.cor || COR_PADRAO,
                fillOpacity: 0.25,
            };
        },
        onEachFeature: function(feature, layer) {
            layer.bindPopup(construirPopup(feature.properties), {
                maxWidth: 320,
                className: 'popup-asg',
            });
        },
    }).addTo(mapa);

    ajustarZoom(camadaResultados);
    mostrarLegenda(fontesPresentes);
}

/* Zoom inteligente */
function ajustarZoom(camada) {
    const bounds = camada.getBounds();
    if (!bounds.isValid()) return;

    const ne = bounds.getNorthEast();
    const sw = bounds.getSouthWest();
    const latDiff = Math.abs(ne.lat - sw.lat);
    const lngDiff = Math.abs(ne.lng - sw.lng);

    if (latDiff < 0.01 && lngDiff < 0.01) {
        mapa.flyTo(bounds.getCenter(), 13, { duration: 1.2 });
    } else {
        mapa.flyToBounds(bounds, { padding: [60, 60], maxZoom: 15, duration: 1.2 });
    }
}

/* Popup estruturado */
function construirPopup(p) {
    const fonte = p.fonte || '';
    const cfg = CORES[fonte] || {};
    const cor = cfg.cor || COR_PADRAO;
    const nomeFonte = cfg.nome || fonte;

    let h = '<div class="popup-content">';
    h += '<div class="popup-header" style="border-left:4px solid ' + cor + ';padding-left:8px">';
    h += '<strong>' + (p.municipio || 'Local') + '</strong>';
    h += '<div class="popup-fonte">' + nomeFonte + '</div></div>';

    if (fonte === 'queimadas') {
        if (p.satelite) h += campo('Satelite', p.satelite);
        if (p.bioma) h += campo('Bioma', p.bioma);
        if (p.frp) h += campo('FRP', p.frp + ' MW');
        if (p.risco_fogo) h += campo('Risco', p.risco_fogo);
        if (p.data_referencia) h += campo('Data', p.data_referencia);
    } else if (fonte === 'funai') {
        if (p.nome) h += campo('Nome', p.nome);
        if (p.etnia) h += campo('Etnia', p.etnia);
        if (p.area_ha) h += campo('Area', p.area_ha + ' ha');
        if (p.fase) h += campo('Fase', p.fase);
    } else if (fonte === 'deter') {
        if (p.classe) h += campo('Classe', p.classe);
        if (p.area_km2) h += campo('Area', p.area_km2 + ' km2');
        if (p.satelite) h += campo('Satelite', p.satelite);
        if (p.data_referencia) h += campo('Data', p.data_referencia);
    } else if (fonte === 'prodes') {
        if (p.classe_nome || p.classe) h += campo('Classe', p.classe_nome || p.classe);
        if (p.ano) h += campo('Ano', p.ano);
        if (p.area_km) h += campo('Area', p.area_km + ' km2');
        if (p.fonte_bioma || p.bioma_fonte) h += campo('Bioma', p.fonte_bioma || p.bioma_fonte);
        if (p.satelite) h += campo('Satelite', p.satelite);
        if (p.data_referencia || p.data_imagem) h += campo('Data', p.data_referencia || p.data_imagem);
    } else if (fonte === 'palmares') {
        if (p.comunidade) h += campo('Comunidade', p.comunidade);
        if (p.ano_certificacao) h += campo('Certificacao', p.ano_certificacao);
        if (p.processo_fcp) h += campo('Processo FCP', p.processo_fcp);
    } else if (fonte === 'icmbio') {
        if (p.nome) h += campo('Nome', p.nome);
        if (p.categoria) h += campo('Categoria', p.categoria);
        if (p.grupo) h += campo('Grupo', p.grupo);
        if (p.area_ha) h += campo('Area', p.area_ha + ' ha');
    }

    if (!p.nome && !p.satelite && !p.classe && p.texto) {
        h += '<div class="popup-texto">' + p.texto + '</div>';
    }

    h += '</div>';
    return h;
}

function campo(label, valor) {
    return '<div class="popup-field"><span>' + label + ':</span> ' + valor + '</div>';
}

/* Legenda */
function mostrarLegenda(fontes) {
    if (legendaControl) mapa.removeControl(legendaControl);
    if (fontes.size === 0) return;

    legendaControl = L.control({ position: 'bottomright' });
    legendaControl.onAdd = function() {
        const div = L.DomUtil.create('div', 'legenda-mapa');
        let html = '<strong>Legenda</strong>';
        fontes.forEach(function(f) {
            const cfg = CORES[f];
            if (cfg) {
                html += '<div class="legenda-item">';
                html += '<span class="legenda-cor" style="background:' + cfg.cor + '"></span>';
                html += cfg.nome + '</div>';
            }
        });
        div.innerHTML = html;
        return div;
    };
    legendaControl.addTo(mapa);
}

/* Limpar e alternar */
function limparMapa() {
    if (camadaResultados) { mapa.removeLayer(camadaResultados); camadaResultados = null; }
    if (legendaControl) { mapa.removeControl(legendaControl); legendaControl = null; }
    ultimoGeoJSON = null;
    resultadosVisiveis = false;
}

function alternarResultados() {
    if (!ultimoGeoJSON) return;
    if (resultadosVisiveis) {
        if (camadaResultados) mapa.removeLayer(camadaResultados);
        if (legendaControl) mapa.removeControl(legendaControl);
        resultadosVisiveis = false;
    } else {
        renderizarGeoJSON(ultimoGeoJSON);
    }
}

/* Botao limpar */
const btnLimpar = L.control({ position: 'topright' });
btnLimpar.onAdd = function() {
    const b = L.DomUtil.create('button', 'btn-limpar-mapa');
    b.innerHTML = 'Limpar mapa';
    b.onclick = function(e) { e.stopPropagation(); e.preventDefault(); limparMapa(); removerCamadasDados(); mapa.flyTo([-22.5, -48.5], 7, { duration: 0.8 }); };
    return b;
};
btnLimpar.addTo(mapa);

/* Camadas de dados via API (rapido, nao WMS) */
const camadasDados = {};

const ID_PARA_COR = {
    queimadas: 'queimadas',
    terras_indigenas: 'funai',
    desmatamento: 'deter',
    prodes: 'prodes',
};

function toggleCamada(fonte) {
    if (camadasDados[fonte]) {
        mapa.removeLayer(camadasDados[fonte]);
        delete camadasDados[fonte];
        return;
    }

    fetch('/api/geo/' + fonte)
        .then(r => r.json())
        .then(geojson => {
            if (!geojson || !geojson.features || geojson.features.length === 0) {
                alert('Nenhum dado disponivel para ' + fonte);
                return;
            }
            const corKey = ID_PARA_COR[fonte] || fonte;
            const cfg = CORES[corKey] || {};
            const cor = cfg.cor || COR_PADRAO;

            camadasDados[fonte] = L.geoJSON(geojson, {
                pointToLayer: function(feature, latlng) {
                    return L.circleMarker(latlng, {
                        radius: 5, fillColor: cor, color: '#fff',
                        weight: 1, fillOpacity: 0.7,
                    });
                },
                style: function() {
                    return { color: cor, weight: 2, fillColor: cor, fillOpacity: 0.2 };
                },
                onEachFeature: function(feature, layer) {
                    layer.bindPopup(construirPopup(feature.properties), {
                        maxWidth: 320, className: 'popup-asg',
                    });
                },
            }).addTo(mapa);
        })
        .catch(() => alert('Erro ao carregar camada ' + fonte));
}

function removerCamadasDados() {
    Object.keys(camadasDados).forEach(function(fonte) {
        mapa.removeLayer(camadasDados[fonte]);
        delete camadasDados[fonte];
    });
    document.querySelectorAll('.camada-check').forEach(function(cb) { cb.checked = false; });
}

/* Painel de camadas */
const painelCamadas = L.control({ position: 'topleft' });
painelCamadas.onAdd = function() {
    const div = L.DomUtil.create('div', 'painel-camadas');
    div.innerHTML = '<strong>Camadas</strong>';

    const fontes = [
        { id: 'queimadas', nome: 'Queimadas', cor: '#ff4444' },
        { id: 'terras_indigenas', nome: 'Terras Indigenas', cor: '#4488ff' },
        { id: 'desmatamento', nome: 'Desmatamento (DETER)', cor: '#ff8c00' },
        { id: 'prodes', nome: 'Desmatamento (PRODES)', cor: '#cc6600' },
    ];


    fontes.forEach(function(f) {
        const label = L.DomUtil.create('label', 'camada-label', div);
        const cb = L.DomUtil.create('input', 'camada-check', label);
        cb.type = 'checkbox';
        cb.onchange = function(e) { e.stopPropagation(); toggleCamada(f.id); };
        const span = L.DomUtil.create('span', '', label);
        span.style.cssText = 'display:inline-block;width:10px;height:10px;border-radius:50%;background:' + f.cor + ';margin:0 6px';
        label.appendChild(document.createTextNode(f.nome));
    });

    L.DomEvent.disableClickPropagation(div);
    L.DomEvent.disableScrollPropagation(div);
    return div;
};
painelCamadas.addTo(mapa);
