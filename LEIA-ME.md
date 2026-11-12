# SOAL Tradutor 0.2

Ferramenta para traduzir os diálogos de **Skies of Arcadia Legends** (GameCube, versão americana).
Lê os textos direto dos arquivos `.sct` do jogo, mostra tudo organizado numa interface no
navegador e grava a tradução de volta, sem limite de tamanho por fala.

## Como usar

1. Instale o **Python 3.8 ou mais novo** (python.org; marque "Add python.exe to PATH").
   Não precisa instalar mais nada.
2. Extraia a ISO. No Dolphin: clique direito no jogo, Propriedades, Sistema de arquivos,
   clique direito em "Disco", Extrair disco inteiro. O GCRebuilder também serve.
3. Dê dois cliques em **`SOAL Tradutor.bat`** (ou rode `python run.py`). A interface abre no
   navegador. Deixe a janela preta aberta enquanto usa.
4. Escolha a pasta extraída (a que contém `files` e `sys`). Na primeira vez o programa leva
   uns 10 a 20 segundos lendo os 258 arquivos.
5. Traduza. Tudo é salvo sozinho.
6. Clique em **Gravar no jogo** e teste no Dolphin abrindo `sys/main.dol` da pasta extraída.

## Usar com o recomp (port nativo)

O programa também grava a tradução no **Skies of Arcadia Legends: Recompiled**
(https://github.com/ogdanimal/SkiesOfArcadiaLegends-Recomp). O port extrai o seu disco para
`%LOCALAPPDATA%\Skies of Arcadia Legends\games\GEAE8P` e lê os arquivos direto dali, então não é
preciso remontar ISO.

Dois jeitos:

- **Só o recomp:** na tela inicial, clique no caminho que aparece em "Recomp encontrado neste
  computador". O projeto fica em `SOAL Tradutor\GEAE8P`, dentro da sua pasta de usuário.
- **Dolphin e recomp juntos:** abra a pasta extraída normalmente e, em "Gravar no jogo", marque
  "Gravar também no recomp". Se o port estiver em modo portátil ou com a pasta de dados em outro
  lugar, cole o caminho ali.

O que muda no recomp:

- Feche o jogo antes de gravar.
- Além dos `.sct` e da fonte, o `sys/fst.bin` (a tabela de arquivos) é atualizado com os tamanhos
  novos. O launcher passa a mostrar o jogo como *modified* e guarda os save states da tradução
  numa pasta própria (`StateSaves/romhack-...`). É de propósito: um save state guarda os tamanhos
  dos arquivos na memória e não deve ser carregado depois que eles mudam.
- Por isso, **save states feitos antes de gravar não aparecem** enquanto a tradução estiver lá, e
  cada gravação que muda o tamanho de algum arquivo começa uma pasta de states nova. Nada é
  apagado. Os saves normais do jogo (cartão de memória) valem sempre: use esses para continuar.
- Em Ajustes há a opção experimental "Manter os save states entre uma gravação e outra", que
  completa os arquivos traduzidos até múltiplos de 32 KB para o tamanho quase nunca mudar.
- Se o launcher pedir o disco de novo (atualização do port, ou "Select Disc"), ele reextrai tudo e
  a tradução some: basta clicar em "Gravar no jogo" outra vez.
- "Devolver os originais" desfaz tudo, inclusive o `fst.bin`.
- O `main.dol` não é tocado.

## O que fica onde

Ao abrir a pasta `X`, o programa cria ao lado dela a pasta `X_traducao`:

| Arquivo | Conteúdo |
|---|---|
| `projeto.json` | suas traduções, nomes de personagens e ajustes (faça backup deste) |
| `originais/` | cópia dos `.sct` e da fonte originais, feita uma única vez |
| `textos.json` | textos extraídos (pode apagar; é refeito) |

| `copias_do_destino/` | cópia do `fst.bin` do recomp e de qualquer arquivo do destino que já não fosse o original |

Ao abrir uma pasta, o programa compara os arquivos com as impressões digitais (SHA-1) do disco
americano original e avisa se algum for diferente, por exemplo quando a pasta já tem uma tradução
gravada.

"Gravar no jogo" sempre parte dos originais guardados, então pode gravar quantas vezes quiser.
"Devolver os originais" desfaz tudo na pasta do jogo.

## Recursos

- Arquivos agrupados por tipo (cidades, masmorras, cenas, batalhas de navio, mundo aberto) com progresso.
- Original e tradução lado a lado, com quem fala, e a marca de 48 colunas na caixa de edição.
- Prévia desenhada com a fonte do próprio jogo; o que passa do limite aparece em vermelho.
- Falas idênticas (mais da metade do jogo se repete) são preenchidas sozinhas e ficam marcadas para revisão.
- Nomes de personagens traduzidos uma vez só, na janela "Nomes".
- Busca em todos os textos, filtros "Faltam", "Revisar" e "Com aviso".
- Exportar e importar planilha CSV (Excel, LibreOffice, Planilhas Google).
- Atalhos: Ctrl+Enter próxima fala, Alt+C copia o original, Alt+R marca para revisar.

## Acentos

A fonte da versão americana só tem ASCII. O programa desenha as letras acentuadas por cima de
15 símbolos que nenhum diálogo usa (`# $ < > @ ^ _ \` { | } = + / "`) e grava a fonte
(`FontData.US`) junto com os textos. O padrão cobre `á à â ã é ê í ó ô õ ú ç É Á Ó`; dá para
trocar em Ajustes. Letras sem lugar saem sem acento e o programa avisa quais foram.

Se algum menu do jogo usar um desses símbolos, ele vai aparecer como a letra acentuada.
Nesse caso, libere o símbolo em Ajustes ou escolha "Gravar sem acento".

## Códigos dentro do texto

- Enter quebra a linha (no jogo é `\n`).
- `…` é o caractere de reticências do jogo (ocupa 2 colunas).
- `\c` no meio de um texto separa páginas ou opções; mantenha onde o original tiver.
- O fim da fala (`\e` ou `\c`) é recolocado sozinho; não precisa digitar.
- Aspas `"assim"` viram as aspas curvas da fonte do jogo.

## Limites desta versão

- Só os diálogos dos `.sct` (pasta `field`). Nomes de itens, magias, menus e textos de batalha
  ficam no executável (`main.dol`) e ainda não são editados.
- Feita e conferida com a versão americana (GEAE8P). A europeia usa outra codificação de texto; o
  programa recusa as outras regiões.
- Não remonta a ISO: o Dolphin roda a pasta extraída. Para gerar ISO, use o GCRebuilder.

## Conferir os arquivos

    python tools/verificar.py "caminho\da\pasta\do\jogo"

Reconstrói cada `.sct` em memória e confere se continua idêntico e se todas as referências do
script seguem apontando para o lugar certo depois que os textos mudam de tamanho. Não grava nada.

## Créditos e licença

- A tabela de parâmetros das instruções de script (`soal/data/instructions.json`) vem do projeto
  **SALSA**, de jahorta (https://github.com/jahorta/SALSA), licença GPL-3.0.
- O suporte ao recomp segue a documentação e o código do port de ogdanimal
  (https://github.com/ogdanimal/SkiesOfArcadiaLegends-Recomp, GPL-3.0) e do ModernGekko / RecompCore.
- Lista completa em `CREDITOS.md`.
- Este programa é distribuído sob a **GPL-3.0** (arquivo `LICENSE`).
- Não inclui nenhum arquivo do jogo. Você precisa da sua própria cópia.
