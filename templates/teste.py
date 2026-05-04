import os
import io
import json
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML, CSS
import geopandas as gpd
import contextily as ctx
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from shapely.geometry import shape

# Comando pra ativar o tailwind:
# npx tailwindcss -i ./templates/tailwind.css -o ./static/relatorio.css --watch

def gerar_mapa_satelite(geojson_data, output_path):
    try:
        df = gpd.GeoDataFrame.from_features(geojson_data["features"])
        df.set_crs(epsg=4326, inplace=True)
        df = df.to_crs(epsg=3857)

        fig, ax = plt.subplots(figsize=(8, 16))
        
        df[df['tipo'] == 'fazenda'].plot(ax=ax, facecolor='#1682f0', alpha=0.3, edgecolor='#1682f0', linewidth=1, zorder=1)
        df[df['tipo'] == 'prodes'].plot(ax=ax, facecolor='#F61247', alpha=0.3, edgecolor='#F61247', linewidth=1, zorder=2)

        legend_elements = [
            Patch(facecolor='#1682f0', edgecolor='#1682f0', alpha=0.3, label='Fazenda'),
            Patch(facecolor='#F61247', edgecolor='#F61247', alpha=0.3, label='Desmatamento (PRODES)')
        ]

        ax.legend(
            handles=legend_elements,
            loc='lower left',
            fontsize=8,
            frameon=True
        )

        minx, miny, maxx, maxy = df.total_bounds
        margin = 0.1
        dx, dy = maxx - minx, maxy - miny
        ax.set_xlim(minx - dx * margin, maxx + dx * margin)
        ax.set_ylim(miny - dy * margin, maxy + dy * margin)

        ctx.add_basemap(
            ax,
            source=ctx.providers.OpenStreetMap.Mapnik,
            attribution=False
        )        
        ax.set_axis_off()
        
        plt.savefig(output_path, 
                    bbox_inches='tight', 
                    pad_inches=0, 
                    dpi=200, 
                    transparent=True)
        plt.close()
        return True
    except Exception as e:
        print(f"❌ Erro: {e}")
        return False

def gerar_pdf_teste():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    
    env = Environment(loader=FileSystemLoader(current_dir))
    template = env.get_template('relatorio.html')

    geojson_exemplo = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-45.266108, -23.515529], [-45.269931, -23.509537], [-45.269886, -23.5069],
                        [-45.271332, -23.504346], [-45.271825, -23.498372], [-45.273061, -23.494938],
                        [-45.273145, -23.48895], [-45.271186, -23.484674], [-45.269869, -23.477438],
                        [-45.271729, -23.472584], [-45.264628, -23.472193], [-45.25664, -23.464127],
                        [-45.251851, -23.463581], [-45.243898, -23.458889], [-45.239209, -23.458733],
                        [-45.2355, -23.456431], [-45.232858, -23.455471], [-45.235256, -23.474655],
                        [-45.235059, -23.480564], [-45.237951, -23.483784], [-45.237222, -23.507183],
                        [-45.239236, -23.507972], [-45.238835, -23.512472], [-45.266108, -23.515529]
                    ]]
                },
                "properties": {"tipo": "fazenda"}
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-45.2646, -23.4924], [-45.2646, -23.4922], [-45.2646, -23.4919],
                        [-45.2644, -23.4919], [-45.2641, -23.4919], [-45.2634, -23.4924],
                        [-45.2631, -23.4937], [-45.2646, -23.4924]
                    ]]
                },
                "properties": {"tipo": "prodes"}
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-45.2306, -23.5231], [-45.2306, -23.5237], [-45.2303, -23.5242],
                        [-45.2304, -23.5251], [-45.2308, -23.5249], [-45.2311, -23.5249],
                        [-45.2309, -23.5246], [-45.2306, -23.5242], [-45.2309, -23.5237],
                        [-45.2312, -23.5231], [-45.2306, -23.5231]
                    ]]
                },
                "properties": {"tipo": "prodes"}
            }
        ]
    }

    logo_path = "file://" + os.path.join(parent_dir, 'static', 'images', 'visiona_logo.svg')
    header_deco_path = "file://" + os.path.join(parent_dir, 'static', 'images', 'header_deco.svg')
    mapa_local_path = os.path.join(parent_dir, 'static', 'images', 'temp_mapa.png')
    
    print("Gerando imagem de satélite...")
    if gerar_mapa_satelite(geojson_exemplo, mapa_local_path):
        mapa_url = "file://" + mapa_local_path
    else:
        mapa_url = ""

    dados = {
        "data_relatorio": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "logo_url": logo_path,
        "header_deco_url": header_deco_path,
        "mapa_url": mapa_url,
        "codigo_imovel": "SP-3555406-B44634FA68E6487396BAD495C826FEA6",
        "indice_risco": 15,
        "lista_riscos": [
                {"nome": "Desmatamento", "valor": 2, "distancia": "34.4km"},
                {"nome": "Queimada", "valor": 6, "distancia": "22.4km"},
                {"nome": "Terra Indígena", "valor": 12, "distancia": "10.1km"},
                {"nome": "Terra Quilombola", "valor": 16, "distancia": "5.3km"},
                {"nome": "Unid. Conservação", "valor": 20, "distancia": "0.0km"},
            ],
        "municipio": "UBATUBA",
        "categoria": "IRU",
        "status": "CANCELADO",
        "condicao": "CANCELADO POR DECISAO ADMINISTRATIVA",
        "area": "1945.7 HA",
        "mod_fiscais": "108.2507",
        "fonte": "SICAR",
        "data_fonte": "2024"
    }

    html_content = template.render(dados)
    css_path = os.path.join(parent_dir, 'static', 'relatorio.css')
    
    stylesheets = []
    if os.path.exists(css_path):
        stylesheets.append(CSS(filename=css_path))
    else:
        print(f"Alerta: O arquivo CSS não foi encontrado.")

    output_filename = os.path.join(current_dir, "relatorio_teste.pdf")
    
    print("Gerando PDF...")
    HTML(string=html_content).write_pdf(
        output_filename, 
        stylesheets=stylesheets
    )
    
    print(f"Relatório salvo com sucesso!")

if __name__ == "__main__":
    gerar_pdf_teste()