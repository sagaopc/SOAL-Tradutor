# SOAL Tradutor 0.8

Ferramenta para traduzir os diálogos, os itens e menus e a introdução de **Skies of Arcadia Legends** (GameCube, versões americana e europeia).
Lê os textos direto dos arquivos `.sct` do jogo, mostra tudo organizado numa interface no
navegador e grava a tradução de volta, sem limite de tamanho por fala.

## Como usar

1. **Windows sem Python:** baixe o `SOAL-Tradutor-x.y-windows.zip` em Releases, descompacte e abra o
   **`SOAL Tradutor.exe`**. Na primeira vez o Windows pode avisar "O Windows protegeu o computador"
   (o `.exe` não tem assinatura digital paga): clique em **Mais informações** e em **Executar assim
   mesmo**. Pule o passo 3.
   **Com Python:** instale o **Python 3.8 ou mais novo** (python.org; marque "Add python.exe to
   PATH"). Não precisa instalar mais nada.
2. Extraia a ISO. No Dolphin: clique direito no jogo, Propriedades, Sistema de arquivos,
   clique direito em "Disco", Extrair disco inteiro. O GCRebuilder também serve.
3. Dê dois cliques em **`SOAL Tradutor.pyw`** (ou em `SOAL Tradutor.bat`). O programa abre numa
   janela própria, sem abas, sem barra de endereço e sem janela preta de console. Para sair, é só
   fechar a janela: o projeto é salvo antes.
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

## Janela própria

A janela usa o motor do Microsoft Edge, que já vem no Windows 10 e 11 (ou o do Google Chrome, se o
Edge não existir), num perfil separado: não mistura com o seu navegador, favoritos ou senhas. Não é
preciso instalar nada além do Python.

- Sem Edge nem Chrome, o programa abre no navegador padrão.
- **`SOAL Tradutor (navegador).bat`** abre no navegador padrão de propósito, com a janela de console
  aberta (útil para ver mensagens de erro).
- Se algo der errado ao abrir, aparece um aviso e os detalhes ficam em `.soal_tradutor.log`, na sua
  pasta de usuário.
- Arquivos exportados (planilha CSV) vão para a pasta Downloads.

## Gerar ISO

Para jogar no Dolphin, não é preciso montar um disco: abra o `sys\main.dol` da pasta do jogo e o
Dolphin roda a pasta extraída direto. Para ter um arquivo `.iso` (guardar, mandar para alguém ou
usar num console), clique em **Gravar no jogo → Gerar ISO…**:

- escolha onde salvar (o padrão é ao lado da pasta do jogo, com "(PT-BR)" no nome);
- deixe marcado **Gravar a tradução no jogo antes**, para a imagem sair com a tradução mais recente;
- a imagem tem o tamanho de um disco de GameCube (cerca de 1,4 GB). Os arquivos entram na mesma
  ordem do disco original, alinhados em 32 KB, e as posições dos que mudaram de tamanho são
  ajustadas na tabela do disco. No fim, o programa confere a imagem antes de entregá-la.

O Dolphin converte a `.iso` para RVZ (bem menor) pelo botão direito no jogo → **Converter arquivo**.

## Ordem da história

No topo da lista de arquivos, troque **Organizar por tipo** por **Ordem da história** para ver os
arquivos agrupados em capítulos, na ordem em que aparecem no jogo: do prólogo no navio do Alfonso
até Soltis. Ajuda a traduzir e revisar seguindo a história. A ordem é aproximada: foi montada pelos
lugares e personagens de cada arquivo. Arquivos usados em vários momentos (o Delphinus, a Ilha
Crescente, o mapa-múndi, batalhas de navio opcionais) ficam em grupos próprios no fim.

O botão **Traduzir automático em ordem…**, logo abaixo, usa o serviço de tradução automática
escolhido em Ajustes para traduzir as falas que faltam, capítulo por capítulo, na ordem da
história. Você escolhe de qual capítulo até qual; a janela mostra quantas falas e caracteres serão
enviados (útil para os limites grátis da DeepL e do Google). Dá para parar a qualquer momento, e
começar de novo continua das que faltam. Tudo o que for traduzido assim fica marcado como
"tradução automática" para revisão.

## O que fica onde

Ao abrir a pasta `X`, o programa cria ao lado dela a pasta `X_traducao`:

| Arquivo | Conteúdo |
|---|---|
| `projeto.json` | suas traduções, nomes de personagens e ajustes (faça backup deste) |
| `originais/` | cópia dos `.sct` e da fonte originais, feita uma única vez; em `originais/extras`, o `main.dol` (ou os `.sot` da versão europeia) e a introdução |
| `textos.json` | textos extraídos (pode apagar; é refeito) |
| `copias_do_destino/` | cópia do `fst.bin` do recomp e de qualquer arquivo do destino que já não fosse o original |

### Mudar a pasta do projeto e guardar cópias

Em **Ajustes → Onde ficam as traduções**:

- **Mover projeto** leva a pasta inteira para outro lugar. O botão **Pasta do tradutor** sugere
  `projetos\<nome>` dentro da pasta do próprio SOAL Tradutor. A pasta antiga só é apagada depois
  que a cópia termina. Depois disso, ao escolher a pasta do jogo de novo, o programa abre o projeto
  no lugar novo; escolher a própria pasta do projeto também funciona. Se o projeto ficar na pasta do
  tradutor, leve a pasta `projetos` junto quando trocar de versão.
- **Cópias de segurança em** guarda uma cópia do `projeto.json` com data e hora a cada 10 minutos
  de trabalho e ao fechar o programa, mantendo as 20 mais recentes e um `projeto.json` igual à
  última. Use outro disco, um pen drive ou uma pasta sincronizada (Google Drive, OneDrive). Para
  voltar uma cópia, feche o programa e coloque o arquivo na pasta do projeto com o nome
  `projeto.json`.

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
- Exportar e importar planilha CSV (Excel, LibreOffice, Planilhas Google). "Exportar falas para
  traduzir" gera uma linha por fala diferente (11.358 no jogo todo), com quem fala, a fala anterior
  e o limite de tamanho; na importação, as falas repetidas são preenchidas sozinhas e as linhas que
  passam do tamanho da caixa são quebradas de novo.
- Atalhos: Ctrl+Enter próxima fala, Alt+C copia o original, Alt+R marca para revisar.

## Tradução automática (opcional)

Para as falas que você considera fáceis, o programa pode pedir uma tradução a um serviço que você
escolhe em **Ajustes > Tradução automática**. Nada é traduzido sozinho: você usa quando quiser.

- **Traduzir automático** em cada fala (ou **Alt+T**) traduz só aquela fala.
- **Traduzir automático as N que faltam**, no topo do arquivo, traduz as falas vazias daquele
  arquivo. Dá para parar no meio. Falas iguais já traduzidas são reaproveitadas.
- Tudo que vem da tradução automática fica marcado como "tradução automática" e aparece no filtro
  **Revisar**. Ao editar a fala, a marca sai.
- As quebras de linha são refeitas para caber na caixa, os códigos do jogo (`\c`, `\e`) são
  preservados e, nos menus, cada opção continua numa linha. Se o serviço estragar um código, a fala
  não é preenchida e o programa avisa.

Serviços:

| Serviço | O que precisa | Usa contexto e glossário |
|---|---|---|
| Ollama ou LM Studio (no seu PC) | o programa instalado e um modelo baixado; endereço `http://localhost:11434/v1` (Ollama) ou `http://localhost:1234/v1` (LM Studio, com o servidor ligado em **Model Server**) | sim: regras de estilo, glossário, gênero de quem fala e fala anterior |
| Claude (API da Anthropic) | chave da API (pago por uso) | sim, igual ao anterior |
| Google Gemini | chave grátis em aistudio.google.com (não pede cartão); o plano grátis limita pedidos por minuto e por dia, e o programa espera sozinho quando o Google pede | sim, igual ao anterior |
| Outros compatíveis com OpenAI | endereço, modelo e chave do serviço | sim, igual ao anterior |
| DeepL | chave da API (plano Developer: pede cartão para identificação e dá um crédito único de caracteres) | só quem fala e a fala anterior |
| Google Cloud Translation | chave da API | não |
| LibreTranslate | endereço de um servidor | não |

Os serviços de modelo de linguagem recebem as regras do projeto: adaptar expressões e gírias em vez
de traduzir ao pé da letra, usar termos de marujo, acertar o gênero e seguir o glossário em
`soal/data/glossario_ptbr.json` (você pode editar) e os nomes da janela **Nomes**.

A chave fica só no seu computador, no arquivo `.soal_tradutor.json` da sua pasta de usuário, e
nunca vai para o projeto nem para a planilha. Os textos das falas são enviados ao serviço escolhido;
com Ollama ou LM Studio, nada sai do seu PC.

Com Ollama ou LM Studio, o programa recebe a resposta aos poucos, espera até 5 minutos sem
resposta (o modelo pode estar carregando) e pede ao modelo para não "pensar" antes de traduzir.
Se mesmo assim a tradução não vier, desligue o raciocínio (thinking) nas opções do modelo, deixe o
**GPU Offload** no máximo e use um contexto pequeno (4096), para o modelo caber na placa de vídeo.

## Revisão com IA

Botão **Revisar com IA…** na lateral. Um serviço de IA lê as suas traduções em sequência (12 falas
por pedido, com quem fala e o original) e aponta só problemas: sentido errado, erro de português,
concordância de gênero, termo ou nome fora do padrão (glossário e janela **Nomes**), palavra que
ficou em inglês ou espanhol, tradução ao pé da letra. Gosto pessoal não conta.

- **Nada é trocado sozinho.** Cada sugestão aparece embaixo da fala, com o tipo, o motivo e o que
  muda (riscado em vermelho, novo em verde): **Aceitar**, **Recusar** ou **Usar e editar**.
- O filtro **Sugestões da IA** em cada arquivo mostra só as falas com sugestão, e o botão
  **Aceitar as N sugestões da IA** aceita todas de uma vez. Na lista de arquivos, o contador "IA"
  mostra onde há sugestões, e o filtro **Com sugestões da IA** separa esses arquivos.
- Escolha o arquivo aberto ou um trecho de capítulos (ou o jogo inteiro). Dá para revisar só as
  falas de tradução automática e as marcadas para revisar.
- Falas que a IA já revisou e que você não mudou ficam de fora na próxima vez (a opção **Revisar de
  novo** inclui essas). Pode parar no meio: começar de novo continua das que faltam. Editar a fala
  descarta a sugestão antiga.
- Falas iguais são revisadas uma vez só. Sugestões que estragam um código do jogo ou mudam o número
  de linhas de um menu são descartadas; as quebras de linha são refeitas para caber na caixa.
- Serve qualquer serviço de modelo de linguagem configurado em Ajustes (Claude, Gemini,
  Ollama/LM Studio ou outro compatível com OpenAI), e pode ser outro que não o que traduz: traduzir
  com a DeepL e revisar com o Gemini, por exemplo. O programa guarda a chave de cada serviço.
  DeepL, Google Cloud Translation e LibreTranslate só traduzem.

## Dublagem: extrair e trocar as vozes

Botão **Dublagem** no topo.

1. **Extrair os sons**: cada voz e cada som do jogo vira um WAV (PCM 16 bits, com a taxa do
   jogo), organizado por personagem:
   - `Personagens/<nome>/vitoria`: falas de vitória com a fanfarra (Vyse, Aika, Fina, Drachma,
     Enrique e Gilder), estéreo;
   - `Personagens/<nome>/batalha`: falas de batalha (gritos de ataque e de dano e nomes dos
     golpes especiais, misturados);
   - `Personagens/Outras vozes de batalha`: falas de batalha de chefes e convidados;
   - `Tripulacao/crNNN`: sons de cada tripulante, com `aparencia.png` mostrando quem é;
     `Tripulacao/comum`: sons das batalhas de navio;
   - `Cenas/<cena>`: sons de cada cena (vozes curtas e efeitos misturados); `Cenas/efeitos`:
     efeitos longos das cenas;
   - `Batalha`, `Campo`, `Musica`, `Outros`.

   Cada som sai uma vez só. O jogo repete muitos sons em vários arquivos (as falas de batalha
   da Aika estão em 72 bancos de som, um para cada formação do grupo); dublando o WAV, o
   programa troca em todos. O `indice_audio.csv` diz de que arquivos do jogo vem cada WAV.
2. **Gravar as falas**: grave por cima do WAV ou em outra pasta. Qualquer taxa, mono ou
   estéreo. **Vale o nome do arquivo, não a pasta**: dá para mover e reorganizar à vontade, e
   pôr texto depois do nome (`0e5f - Aika grito.wav`). Tente manter a duração parecida.
3. **Importar**: o programa pega só os WAV que mudaram e guarda no projeto (pasta `dublagem`).
   A janela lista os sons dublados com o personagem ou a cena, toca o original e o dublado e
   avisa quando a fala nova é bem mais longa.
4. **Gravar no jogo** devolve cada som aos arquivos originais do jogo de onde saiu, codificado
   em DSP ADPCM (o formato do GameCube), junto com a tradução, também no recomp (com a tabela
   de arquivos atualizada) e na ISO. Os originais ficam guardados em `originais/extras`;
   **Restaurar os originais** devolve os sons originais. O patch de tradução leva a dublagem.

Como os personagens foram identificados: as falas de vitória têm o número do personagem no nome
(1 = Vyse … 6 = Gilder); as falas de batalha formam grupos fixos nos 72 bancos (Vyse, Aika e
Fina em todos; Drachma, Enrique e Gilder se revezando), conferidos pelo tom e pelo timbre da voz
comparados com as falas de vitória de cada um. Nos bancos, o som trocado ocupa o lugar do
original e os outros sons não mudam; o programa avisa quando um banco cresce mais de 25%,
porque o console guarda os bancos numa memória de som limitada.

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

## Itens, menus e sistema

No fim da lista de arquivos, o grupo **Itens, menus e sistema** traz os textos que não são
diálogos: nomes e descrições de armas, armaduras, acessórios, itens, itens especiais, magias e
supergolpes, peças e itens do navio, tripulantes, golpes dos inimigos, descobertas, diário de
bordo, lugares, lojas, procurados e lendas, menus, mensagens de batalha e do cartão de memória, e os
nomes dos seis personagens. Eles se traduzem como as falas: texto ao lado do original, filtros,
planilha e tradução automática (que recebe a informação de onde o texto aparece e do tamanho).

- **Versão americana**: esses textos ficam no executável (`sys/main.dol`), que é gravado junto com
  os diálogos. Cada nome de item tem um campo de tamanho fixo (em geral 16 letras), e a tela mostra
  quantas letras ainda cabem. As descrições e as mensagens ficam em blocos: um texto pode crescer
  desde que outro do mesmo bloco encurte, e a tela mostra quanto do bloco está ocupado. O que não
  couber fica em inglês e aparece no relatório da gravação. Reticências (…) contam 2 letras.
- **Versão europeia**: ficam nos arquivos `english.sot`, `spanish.sot`, `french.sot` e
  `german.sot`. A tradução vai para o idioma escolhido em Ajustes, sem limite de tamanho por texto.
- Alguns textos do original têm espaços nas pontas para ficar centralizados na tela; faça o mesmo
  na tradução. Códigos como `%s` (um valor que o jogo preenche) e `\c` precisam continuar no texto.
- Nomes de inimigos comuns não aparecem como texto no jogo, por isso não estão na lista; os nomes
  dos navios inimigos e dos golpes, sim.

## Sugestões de nomes

Nos nomes curtos (itens, armas, armaduras, peças do navio, lugares, lojas) e nos nomes de quem
fala, o programa sugere uma tradução tirada de um vocabulário próprio, sem precisar de serviço
de tradução: “Valuan Soldier” → **Soldado Valuano**, “Boomerang” → **Bumerangue**, “Sacri Crystal”
→ **Cristal Sacri**, “Iron Ring” → **Anel de Ferro**, “Aika's Shorts” → **Shorts da Aika**.

- A sugestão aparece embaixo do campo vazio; clique nela para usar e ajuste se quiser.
- **Usar as N sugestões de nomes**, no topo de cada lista de itens, preenche todos os vazios de uma
  vez; em **Nomes**, o botão **Usar as sugestões nos nomes vazios** faz o mesmo com quem fala. O que
  vem da sugestão fica marcado como “tradução automática”, no filtro **Revisar**.
- Nomes próprios (Vyse, Drachma, Sacri, Yafutoma) ficam como estão. Palavra que o vocabulário não
  conhece fica em inglês na sugestão.
- O vocabulário fica em `tools/vocabulario_fonte.txt`; para acrescentar palavras, edite o arquivo e
  rode `python tools/gerar_vocabulario.py`.

## Termos padronizados

Expressões que se repetem no jogo devem ter sempre a mesma tradução: “Blue Rogues” é sempre
**Piratas Azuis**, “Black Pirates” é **Piratas Negros**, “Moon Stone” é **Pedra da Lua**. O botão
**Termos**, no topo, abre a lista. O projeto já vem com os termos mais comuns do jogo, e você pode
mudar, apagar ou acrescentar os seus.

- **Inglês** e **Português**: separe singular e plural com “/” (`Blue Rogue / Blue Rogues` →
  `Pirata Azul / Piratas Azuis`).
- **Traduções a trocar**: as traduções diferentes que podem ter aparecido (Ladinos Azuis, Rogues
  Azuis…), separadas por vírgula.
- **Conferir as traduções** mostra, para cada termo, quantas falas estão no padrão, quantas usam uma
  das traduções a trocar e quantas usam outra coisa. **Padronizar** troca as conhecidas pelo termo
  escolhido, respeitando singular, plural, letra maiúscula e quebra de linha, sem mudar o estado das
  falas. A forma feminina das traduções a trocar também é trocada (Ladina Azul, Bandidas Azuis). As
  demais aparecem numa lista; clique para abrir e corrigir à mão.
- **Padronizar** também tira de todas as falas o **¡** e o **¿** do espanhol, que aparecem quando a
  tradução automática parte do texto espanhol, e deixa as reticências com três pontos (“……” vira
  “…”). A tradução automática já não faz isso, e uma fala que ainda tenha ganha um aviso.
- Uma fala cujo original tem o termo e cuja tradução não segue o padrão ganha um **aviso** (filtro
  **Com aviso**).
- A tradução automática recebe os termos e usa as formas escolhidas.

## Patch de tradução

O patch leva a sua tradução para outro jogo da mesma versão: outra ISO, outra pasta extraída ou
outro recomp (de outro computador, por exemplo). Ele guarda só o seu trabalho: as traduções, os
nomes de quem fala, os termos, os ajustes e as imagens que você editou. Não leva arquivos do jogo.

Na janela **Gravar no jogo**, clique em **Patch…**.

- **Criar patch**: salva um arquivo `.soalpatch` com o projeto aberto. É pequeno (alguns
  megabytes, mesmo com as imagens).
- **Aplicar patch**: escolha o patch e o jogo que recebe a tradução.
  - **ISO**: a original não muda. O programa monta uma ISO nova, traduzida (precisa de cerca de
    3 GB livres enquanto trabalha).
  - **Pasta do jogo extraído** ou **pasta do recomp** (a do programa ou a de dados): a tradução é
    gravada nos arquivos. O programa cria um projeto próprio para esse jogo, com os originais, que
    aparece na lista de recentes: por ele dá para devolver os originais ou reaplicar um patch novo.
    No recomp europeu, o idioma do jogo é ajustado.
- Se o texto em inglês de alguma fala for diferente no jogo de destino, a tradução entra marcada
  para revisar.

## Imagens com texto

Algumas palavras do jogo não são texto: estão desenhadas em imagens. O botão **Imagens**, no topo,
reúne as que têm texto em inglês:

- **Tela-título e abertura**: o logotipo com New Game, Continue e PRESS START, o “Presented by
  SEGA” e o aviso de luzes piscando.
- **Início do jogo**: o prólogo que aparece ao começar um jogo novo (“The age of exploration has
  dawned upon the world of Arcadia…”). Não é vídeo: é uma imagem.
- **Fim de jogo**: GAME OVER.
- **Batalha** e **Batalha de navios**: os comandos (Attack, Guard, Run, Item, Focus…), MISS, Hp, Mp e Lv.
- **Menus e lojas**: os rótulos da loja e do status (Attack, Agility, Next, Gold, LEVEL UP,
  NEW RECORD…) e a tela de menu.
- **Mapa-múndi**: os nomes das regiões (Mid Ocean, Valuan Empire, The Dark Rift…).
- **Outro arquivo**: procure qualquer arquivo de imagens do jogo pelo nome (por exemplo um mapa
  `a002a`) para editar as imagens dele.

Clique numa imagem para abrir o editor:

- **Apagar área**: arraste sobre o texto em inglês. Preencha com transparente, com a cor em volta
  (bom para texto sobre fundo liso) ou com uma cor escolhida.
- **Texto**: escreva, clique na imagem para posicionar e arraste para ajustar. Escolha fonte,
  tamanho, cor, contorno, sombra e espaço entre letras. **Sem suavizar** deixa as letras com borda
  dura, como nos rótulos pequenos do jogo. **Aplicar texto** fixa o texto na imagem.
- **Conta-gotas**: pega uma cor da imagem para o texto.
- **Original** (segure): mostra a imagem original para comparar. **Desfazer** (Ctrl+Z) volta um passo.
- Para um trabalho mais caprichado, **Baixar PNG**, edite no seu programa de imagens (GIMP,
  Photoshop, Krita…) sem mudar o tamanho e use **Abrir PNG editado…**.

**Salvar no projeto** guarda a imagem e mostra **como fica no jogo**: o GameCube guarda muitas
imagens comprimidas, e algumas perdem um pouco de qualidade. As imagens vão para o jogo ao clicar
em **Gravar no jogo**, junto com o resto, e **Restaurar originais** também as desfaz.

A mesma imagem que aparece em vários arquivos é traduzida uma vez só: os nomes das regiões se repetem
em todos os arquivos do mapa-múndi, e todos recebem a sua versão.

Na versão europeia, cada imagem tem uma cópia por idioma, e a janela mostra a cópia do idioma
escolhido em **Ajustes** (o mesmo que recebe as falas): é ela que vai para o jogo. Edite sempre
essa cópia: nos menus, a disposição das palavras muda de um idioma para outro (“Foc/us” no inglês,
“Enfo/que” no espanhol), e o jogo recorta cada palavra do lugar dela. O botão **Inglês** (segure)
mostra a imagem inglesa para comparar, e a dica de cada imagem traz o texto em inglês. No prólogo,
os quatro idiomas ficam no mesmo arquivo, e a janela mostra só a imagem do idioma escolhido.

**Versão europeia: o jogo tem de estar no idioma que recebeu a tradução.** Se a tradução foi
gravada no lugar do espanhol e o jogo está em inglês, aparece o inglês original (textos e imagens).
No recomp, o idioma é a opção da aba **Language** das configurações dele (`[Skies] Language` no
`Dolphin.ini`); o programa ajusta sozinho ao gravar. Se você mudar a pasta do recomp de lugar, use
**Trocar a pasta do recomp** na janela **Gravar no jogo**. No Dolphin, escolha o idioma em
Configurações → GameCube → Idioma do sistema.

## Remaster: texturas e modelos 3D

O botão **Remaster** tira do jogo as texturas e os modelos 3D para você melhorar fora do programa.
Ele lê o jogo do jogo aberto ou do recomp, com a tradução que já está gravada, e grava numa pasta à
sua escolha:

- **`texturas/GEA/…`**: cada textura com o nome que o recomp (e o Dolphin) procura nos pacotes de
  texturas HD, como `tex1_128x128_m_57ca8a0b140a3cf1_14.png`. Melhore a imagem em qualquer
  resolução (2×, 4×, redesenhada), **mantenha o nome** e a proporção, e instale. O jogo passa a
  usar a nova, sem regravar nada. A mesma textura usada em vários arquivos sai uma vez só: melhorando
  ela, muda em todos os lugares (a roupa do Vyse nas batalhas e nas cenas, por exemplo).
- **`modelos/…`**: cada modelo em glTF 2.0 (`.glb`): personagens, inimigos, objetos e construções,
  com esqueleto (ossos e pesos), materiais e texturas embutidas. No Blender: Arquivo › Importar ›
  glTF 2.0. O nome de cada imagem nos materiais é o nome da textura na pasta `texturas`.
- **`cenarios/…`**: cada lugar inteiro (cidades, interiores, masmorras, cenários de batalha), com
  os objetos e os moradores na posição do jogo.
- **`indice_texturas.csv`**: de que arquivo vem cada textura e quais modelos a usam.

Ficam de fora a malha de colisão do chão e as caixas invisíveis que o jogo usa como gatilho
(escadas, portas, scripts). As peças com reflexo (que o jogo calcula pela câmera) recebem
coordenadas aproximadas para aparecerem no Blender.

**Instalar texturas melhoradas no recomp**: na mesma janela, escolha a pasta com as texturas (pode
ser só as que você mudou) e clique **Instalar no recomp**. Elas vão para
`Load/Textures/GEA/SOAL Tradutor` e as texturas HD são ligadas (`GFX.ini`, `HiresTextures`). Os
pacotes que você já importou pelo recomp continuam. Também dá para importar pelo próprio recomp:
Configurações › Gráficos › Texture pack › Import a folder….

**Conferir os nomes**: com `DumpTextures = True` no `GFX.ini` do recomp, ele grava em
`Dump/Textures` as texturas que aparecem enquanto você joga. O botão **Conferir com as texturas
despejadas pelo recomp** diz quantas delas têm o mesmo nome de uma textura extraída.

O jogo inteiro leva de 15 a 30 minutos e ocupa alguns GB; dá para extrair só uma parte (personagens,
cenários, efeitos…). Algumas imagens de menu que o jogo copia da tela mudam de nome a cada vez e
não podem ser trocadas por pacote.

## Introdução

A **Introdução** (“In a world shrouded in mystery…”) são 11 páginas que o jogo mostra como imagens.
Cada página aparece ao lado do campo da tradução, e o painel da direita mostra como ela fica com o
texto novo. Quebre a linha onde quiser (2 linhas, como no original). Na gravação, a tradução é
desenhada com a fonte escolhida em **Ajustes → Fonte da introdução**: Uncial, parecida com a da
versão americana, ou Gótica, parecida com a da europeia. Na versão europeia, as páginas vão para o
idioma escolhido em Ajustes.

## Nomes de quem fala

Em **Nomes**, o botão **Traduzir automático os nomes que faltam** traduz os cargos e descrições
(“Valuan Soldier”, “Old Man”, “Merchant Ship”...) com o serviço escolhido em Ajustes. Nomes
próprios (Vyse, Aika, Drachma) ficam iguais e continuam em branco na lista. Revise o resultado: o
nome traduzido vale para todas as falas daquele personagem.

## Limites desta versão

- Na versão americana, os textos de itens e menus precisam caber no espaço do `main.dol`.
- O recomp não foi testado com o `main.dol` traduzido.
- Versões americana (GEAE8P) e europeia (GEAP8P). A japonesa não é aceita.
- No recomp (port nativo), a tradução vai para o jogo importado da mesma versão do projeto (GEAE8P ou GEAP8P).
- Remaster: os modelos são extraídos, mas ainda não voltam para o jogo. Texturas melhoradas entram
  pelo pacote de texturas HD; modelos com mais polígonos precisam de um importador (próximo passo).
  As animações (NMDM) ainda não são extraídas.
- Dublagem: as vozes curtas das cenas e as da tripulação não estão separadas por personagem
  (vêm por cena e por tripulante, misturadas com efeitos). Fala dublada muito mais longa que a
  original pode ser cortada pela cena.

## Versão europeia

Escolha a pasta da versão europeia extraída (com `files` e `sys`) como se fosse a americana: o
programa reconhece o disco (GEAP8P) e cria um projeto separado. Com um projeto aberto, use o botão
da versão na barra de cima (“Americana ▾” ou “Europeia ▾”) para trocar de jogo ou abrir outra pasta.

- Cada fala do disco europeu existe em inglês, francês, alemão e espanhol. O programa mostra a
  inglesa para você traduzir. Em **Ajustes → Idioma que recebe a tradução** você escolhe em qual
  idioma do jogo a tradução é gravada (inglês, espanhol, francês ou alemão); no jogo, escolha esse
  idioma no menu. Os outros idiomas ficam intactos, e as falas ainda não traduzidas aparecem no
  idioma original do lugar escolhido. Os nomes de quem fala que você não traduziu em **Nomes**
  ficam como estão nesse idioma.
- As chaves das falas (`MA0150001` e outras) e os nomes dos arquivos são os mesmos da versão
  americana. Por isso a tradução feita na americana passa para a europeia: abra o projeto europeu,
  vá em **Planilha → Trazer de outro projeto** e escolha a pasta do projeto americano. As falas cujo
  texto em inglês é diferente entre as versões chegam marcadas para revisar.
- Em **Ajustes → Tradução automática → Traduzir a partir do**, a tradução automática pode partir do
  espanhol (ou do francês, do alemão) em vez do inglês. O espanhol já marca o gênero das palavras,
  o que ajuda serviços como DeepL e Google, que não recebem quem fala. O texto nesse idioma aparece
  embaixo do original em inglês.
- A fonte europeia já tem as letras acentuadas (á, ã, ç, õ...), então não há troca de símbolos nem
  limite de acentos.
- A planilha CSV da americana também pode ser importada direto no projeto europeu, mas aí as
  falas com o inglês diferente não ganham a marca de revisar.

## Conferir os arquivos

    python tools/verificar.py "caminho\da\pasta\do\jogo"

Reconstrói cada `.sct` em memória e confere se continua idêntico e se todas as referências do
script seguem apontando para o lugar certo depois que os textos mudam de tamanho. Não grava nada.

## Créditos e licença

- A tabela de parâmetros das instruções de script (`soal/data/instructions.json`) vem do projeto
  **SALSA**, de jahorta (https://github.com/jahorta/SALSA), licença GPL-3.0.
- As posições das tabelas de itens no `main.dol` americano vêm do **ALX**, de Marcel Renner
  (https://github.com/Taikocuya/ALX), licença GPL-3.0.
- A introdução usa as fontes livres Uncial Antiqua e UnifrakturMaguntia (SIL Open Font License).
- O suporte ao recomp segue a documentação e o código do port de ogdanimal
  (https://github.com/ogdanimal/SkiesOfArcadiaLegends-Recomp, GPL-3.0) e do ModernGekko / RecompCore.
- Lista completa em `CREDITOS.md`.
- Este programa é distribuído sob a **GPL-3.0** (arquivo `LICENSE`).
- Não inclui nenhum arquivo do jogo. Você precisa da sua própria cópia.
