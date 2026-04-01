Antes de rodar os arquivos é necessário rodar: pip install git+https://github.com/urbanogilson/SICAR

Primeiro execute o coletor_sicar.py para baixar os dados 
Segundo execute processar_sicar.py para converter o ZIP em geojson
Terceiro execute importar_sicar.py que vai inserir no banco os dados do sicar gerados em geojson

O arquivo dividir geojson foi criado apenas para validar se os dados foram baixados corretamente pois o arquivo completo não tem como abrir no vscode por ser muito grande


Coisas a fazer: mudar para os dados serem baixados direto na pasta dados