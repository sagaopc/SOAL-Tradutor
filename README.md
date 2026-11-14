# SOAL Tradutor

Ferramenta para traduzir **Skies of Arcadia Legends** (GameCube, versões americana e europeia): os
diálogos, os nomes e descrições de itens, armas, magias e peças do navio, os menus e mensagens, e as
páginas da introdução do começo do jogo.
Ela lê os textos direto dos arquivos do jogo, mostra tudo organizado numa interface numa janela
própria e grava a tradução de volta; nos diálogos, **sem limite de tamanho por fala**. Também monta
a imagem de disco (`.iso`) já traduzida.

Funciona com o jogo extraído para o **Dolphin** e com o port nativo
**[Skies of Arcadia Legends: Recompiled](https://github.com/ogdanimal/SkiesOfArcadiaLegends-Recomp)**.

> Nenhum arquivo do jogo está neste repositório. Você precisa da sua própria cópia do disco.

## Download

Em **[Releases](../../releases)**:

- **`SOAL-Tradutor-x.y.z-windows.zip`**: para Windows 10 e 11, sem instalar nada. Abra o
  `SOAL Tradutor.exe`.
- `SOAL-Tradutor-x.y.z.zip`: o código, para qualquer sistema com Python 3.8 ou mais novo.

Na primeira vez, o Windows pode mostrar "O Windows protegeu o computador", porque o `.exe` não tem
assinatura digital paga: clique em **Mais informações** e depois em **Executar assim mesmo**.

O `.exe` é compilado pelo GitHub Actions a partir deste código, a cada versão
(`.github/workflows/compilar.yml`).

## Começando

1. No Windows, baixe o zip `-windows`, descompacte e abra o **`SOAL Tradutor.exe`**. Em outros
   sistemas, instale o **Python 3.8 ou mais novo** e abra o **`SOAL Tradutor.pyw`** do zip do código.
2. O programa abre numa janela própria (usa o motor do Edge que já vem no Windows); para sair,
   feche a janela.
3. Escolha a pasta do jogo extraído (a que contém `files` e `sys`) ou, se o recomp estiver
   instalado, clique no jogo dele que aparece na tela inicial.
4. Traduza. Tudo é salvo sozinho, fora da pasta do jogo.
5. Clique em **Gravar no jogo** e teste: no Dolphin, abra o `sys\main.dol` da pasta do jogo; no
   recomp, inicie o jogo normalmente.
6. Quando quiser um disco, use **Gravar no jogo → Gerar ISO…**.

O manual completo está em **[LEIA-ME.md](LEIA-ME.md)**.

## O que ele faz

- Reconstrói os `.sct` e corrige todas as referências internas do script, então cada fala pode ter
  o tamanho que precisar. O editor antigo (SOALEditor) só aceitava texto dentro do espaço original.
- Arquivos agrupados por tipo (cidades, masmorras, cenas, batalhas de navio, mundo aberto) ou na
  **ordem da história**, em capítulos do prólogo até o final, com progresso por arquivo e geral.
- Original e tradução lado a lado, com o nome de quem fala.
- Prévia desenhada com a **fonte do próprio jogo**, com o limite da caixa de diálogo marcado.
- Falas repetidas preenchidas sozinhas, nomes de personagens traduzidos uma vez só, busca global e
  filtros.
- Exportar e importar planilha CSV, com uma linha por fala diferente; na importação as repetições
  são preenchidas e as linhas longas são quebradas sozinhas.
- **Itens, menus e sistema**: nomes e descrições de armas, armaduras, acessórios, itens, magias,
  supergolpes, peças do navio e tripulantes, golpes dos inimigos, descobertas, diário de bordo,
  lugares, lojas, procurados, menus e mensagens do cartão de memória. Na versão americana eles ficam
  no `main.dol` e cada texto tem um espaço máximo (a tela mostra quanto sobra); na europeia ficam nos
  arquivos `.sot` e não têm limite.
- **Introdução**: as 11 páginas do começo do jogo são imagens. A tradução é desenhada com uma fonte
  parecida com a original, e a tela mostra como a página fica.
- Tradução automática dos **nomes de quem fala** que faltam (cargos como “Valuan Soldier” são
  traduzidos; nomes próprios ficam iguais).
- Letras acentuadas desenhadas na fonte do jogo, que na versão americana não tem acentos. Na
  europeia, a fonte já tem todas as letras do português.
- **Versão europeia**: mostra só as falas em inglês (francês, alemão e espanhol ficam intactos) e
  traz a tradução feita na americana com **Planilha → Trazer de outro projeto**, marcando para
  revisar as falas cujo inglês muda entre as versões.
- Tradução automática opcional, fala por fala, por arquivo ou por capítulos na ordem da história,
  com o serviço que você escolher (Ollama/LM Studio no seu PC, Claude, DeepL, Google ou
  LibreTranslate). Mostra o tempo por fala e quanto falta, para sozinha se o serviço deixar de
  responder e continua de onde parou. As falas ficam marcadas para revisão, e cada serviço guarda a
  própria configuração. As chaves ficam só no seu computador.
- **Gerar ISO**: monta a imagem de disco de GameCube a partir da pasta extraída, com as posições dos
  arquivos traduzidos ajustadas, e confere a imagem no fim.
- Pasta do projeto separada do jogo, que pode ser movida (por exemplo, para dentro da pasta do
  tradutor), e **cópias de segurança automáticas** do projeto em outra pasta.
- Guarda os originais e permite devolvê-los a qualquer momento.

## Conferência

`tools/verificar.py` reconstrói cada `.sct` em memória e confere se o arquivo continua idêntico e
se todas as referências do script seguem apontando para o lugar certo depois que os textos mudam de
tamanho. Com o disco americano: 258 arquivos, 25.347 textos e 78.937 referências conferidas; com o
europeu: 258 arquivos, 98.942 textos (quatro idiomas) e 241.488 referências.

    python tools/verificar.py "caminho\da\pasta\do\jogo"

## Estado

Versão 0.8, em teste. A leitura e a reconstrução dos arquivos foram conferidas em todos os
arquivos do jogo, e a geração da ISO foi conferida extraindo a imagem de volta. O jogo traduzido
ainda precisa ser testado rodando, principalmente as letras acentuadas e a ISO num console.
Relatos são bem-vindos em [Issues](../../issues).

As mudanças de cada versão estão nas notas de cada [release](../../releases).

Limites: na versão americana, os textos de itens e menus precisam caber no espaço do `main.dol`;
nomes de inimigos não aparecem como texto no jogo; versões americana (GEAE8P) e europeia (GEAP8P);
o recomp só roda a americana.

## Créditos

Veja **[CREDITOS.md](CREDITOS.md)**. Em resumo: a tabela de instruções de script vem do projeto
[SALSA](https://github.com/jahorta/SALSA), de jahorta, e o suporte ao recomp segue a documentação e
o código do port de [ogdanimal](https://github.com/ogdanimal/SkiesOfArcadiaLegends-Recomp), e as
posições das tabelas de itens no `main.dol` vêm do [ALX](https://github.com/Taikocuya/ALX), de
Marcel Renner.

## Licença

[GPL-3.0](LICENSE).
