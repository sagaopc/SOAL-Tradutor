# SOAL Tradutor

Ferramenta para traduzir os diálogos de **Skies of Arcadia Legends** (GameCube, versão americana).
Ela lê os textos direto dos arquivos de script `.sct` do jogo, mostra tudo organizado numa interface
no navegador e grava a tradução de volta, **sem limite de tamanho por fala**.

Funciona com o jogo extraído para o **Dolphin** e com o port nativo
**[Skies of Arcadia Legends: Recompiled](https://github.com/ogdanimal/SkiesOfArcadiaLegends-Recomp)**.

> Nenhum arquivo do jogo está neste repositório. Você precisa da sua própria cópia do disco.

## Download

Baixe o `SOAL-Tradutor-x.y.zip` mais recente em **[Releases](../../releases)**.

## Começando

1. Instale o **Python 3.8 ou mais novo** ([python.org](https://www.python.org/downloads/), marcando
   "Add python.exe to PATH"). Não precisa de mais nada.
2. Descompacte o zip e dê dois cliques em **`SOAL Tradutor.bat`** (ou rode `python run.py`).
3. Escolha a pasta do jogo extraído (a que contém `files` e `sys`) ou, se o recomp estiver
   instalado, clique no jogo dele que aparece na tela inicial.
4. Traduza. Tudo é salvo sozinho.
5. Clique em **Gravar no jogo** e teste.

O manual completo está em **[LEIA-ME.md](LEIA-ME.md)**.

## O que ele faz

- Reconstrói os `.sct` e corrige todas as referências internas do script, então cada fala pode ter
  o tamanho que precisar. O editor antigo (SOALEditor) só aceitava texto dentro do espaço original.
- Arquivos agrupados por tipo (cidades, masmorras, cenas, batalhas de navio, mundo aberto), com
  progresso por arquivo e geral.
- Original e tradução lado a lado, com o nome de quem fala.
- Prévia desenhada com a **fonte do próprio jogo**, com o limite da caixa de diálogo marcado.
- Falas repetidas preenchidas sozinhas, nomes de personagens traduzidos uma vez só, busca global e
  filtros.
- Exportar e importar planilha CSV.
- Letras acentuadas desenhadas na fonte do jogo, que na versão americana não tem acentos.
- Guarda os originais e permite devolvê-los a qualquer momento.

## Conferência

`tools/verificar.py` reconstrói cada `.sct` em memória e confere se o arquivo continua idêntico e
se todas as referências do script seguem apontando para o lugar certo depois que os textos mudam de
tamanho. Com o disco americano: 258 arquivos, 25.347 textos e 78.937 referências conferidas.

    python tools/verificar.py "caminho\da\pasta\do\jogo"

## Estado

Versão 0.2, em teste. A leitura e a reconstrução dos arquivos foram conferidas em todos os
arquivos do jogo; o jogo traduzido ainda precisa ser testado rodando, principalmente as letras
acentuadas. Relatos são bem-vindos em [Issues](../../issues).

Limites: só os diálogos dos `.sct` (itens, magias e menus ficam no `main.dol` e ainda não são
editados) e só a versão americana (GEAE8P).

## Créditos

Veja **[CREDITOS.md](CREDITOS.md)**. Em resumo: a tabela de instruções de script vem do projeto
[SALSA](https://github.com/jahorta/SALSA), de jahorta, e o suporte ao recomp segue a documentação e
o código do port de [ogdanimal](https://github.com/ogdanimal/SkiesOfArcadiaLegends-Recomp).

## Licença

[GPL-3.0](LICENSE).
