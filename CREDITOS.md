# Créditos

O SOAL Tradutor foi feito por **[sagaopc](https://github.com/sagaopc)**, com a ajuda do Claude
(Anthropic), em cima do trabalho de outras pessoas da comunidade de Skies of Arcadia e de
recompilação. Obrigado a todas elas.

## Código e dados usados

- **[SALSA](https://github.com/jahorta/SALSA)**, de **jahorta**: Skies of Arcadia Legends Script
  Assistant (GPL-3.0). A tabela de parâmetros das instruções de script
  (`soal/data/instructions.json`) foi derivada das definições do SALSA. É graças a esse trabalho de
  engenharia reversa que o programa consegue achar todas as referências do script e mover os textos
  com segurança. O formato dos arquivos `.sct` e a compressão AKLZ também foram estudados no código
  do SALSA.

## Documentação e código consultados

- **[Skies of Arcadia Legends: Recompiled](https://github.com/ogdanimal/SkiesOfArcadiaLegends-Recomp)**,
  de **ogdanimal** (GPL-3.0): a documentação e o código do launcher explicaram onde o port guarda o
  jogo importado, como ele lê os arquivos e como separa os save states de um jogo modificado.
  Nenhum código do port foi copiado.
- **[ModernGekko](https://github.com/ExpansionPak/ModernGekko)** e
  **[RecompCore](https://github.com/ExpansionPak/RecompCore)**, de **ExpansionPak**: o leitor de
  pasta extraída usado pelo port.
- **[Puyo Tools](https://github.com/nickworonekin/puyotools)**: referência original do formato AKLZ.

## Ferramenta anterior

- **SOALEditor 0.4**, de **ADnova** (2011): o editor de dados e diálogos que este programa
  substitui para tradução. Nenhum código dele foi usado; a análise dele mostrou o que precisava
  mudar.

## Ferramentas recomendadas

- **[Dolphin](https://dolphin-emu.org/)**: extrair o disco e testar a tradução.
- **GCRebuilder**, de **BSV**: extrair e remontar imagens de GameCube.

## Licença

O SOAL Tradutor é distribuído sob a GPL-3.0 (arquivo `LICENSE`), a mesma licença do SALSA, de onde
vem a tabela de instruções.

Skies of Arcadia Legends é marca da SEGA. Este projeto não tem relação com a SEGA e não inclui
nenhum arquivo do jogo.
