<p align="center">
  <img src="docs/images/icon.svg" width="72" alt="">
</p>

<h1 align="center">Sottovoce</h1>

<p align="center"><strong>Trascrizione delle call sul tuo computer, che ti mostra dove il testo non è affidabile.</strong></p>

<p align="center">
  <a href="https://github.com/thetouchsite/sottovoce/actions/workflows/tests.yml"><img src="https://github.com/thetouchsite/sottovoce/actions/workflows/tests.yml/badge.svg" alt="test"></a>
  <a href="https://github.com/thetouchsite/sottovoce/releases"><img src="https://img.shields.io/github/v/release/thetouchsite/sottovoce" alt="release"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/licenza-MIT-blue" alt="licenza MIT"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/piattaforme-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey" alt="Windows, Linux, macOS">
</p>

<p align="center">
  <a href="https://thetouchsite.github.io/sottovoce/">Documentazione (in inglese)</a> ·
  <a href="#avvio-rapido">Avvio rapido</a> ·
  <a href="#confronto">Confronto</a> ·
  <a href="README.md">English</a>
</p>

![Un giro di Sottovoce su call inventate: la schermata iniziale, il riassunto di una call, la striscia della call, tre voci nominate nel pannello Voci, una call registrata su due tracce](docs/images/demo.gif)

Trascini sulla pagina una call registrata, oppure registri la call da lì. Ottieni la trascrizione, chi ha detto cosa, un riassunto, gli appunti per la cartella del cliente, l'email di follow-up e una mappa dei punti da ricontrollare. Whisper large-v3 sulla tua GPU. Niente esce dalla macchina.

## Perché Sottovoce

- **Ti mostra dove il testo è debole.** La *striscia della call* disegna tutta la registrazione in una banda: parlato, silenzio, frasi tolte, righe corrette. Clicchi in un punto e ascolti da lì.
- **Toglie quello che nessuno ha detto.** Sul silenzio Whisper scrive sottotitoli imparati da YouTube: *"Grazie per la visione"*. Sottovoce li toglie solo dove l'audio è molto sotto il parlato, ed elenca ogni rimozione. Su un test pubblico con pause lunghe aggiunge 47 parole che nessuno ha detto, dove Whisper da solo ne aggiunge 318 ([misurato](docs/benchmarks.md#long-pauses)).
- **Sa chi ha parlato.** Una call registrata qui tiene il tuo microfono e la call su due tracce, da qualsiasi app su Windows, da una scheda del browser altrove: *Tu* e *Loro* sono misurati, non indovinati. Su qualsiasi registrazione separa le voci senza account e senza token, con un [errore del 12% su riunioni pubbliche](docs/benchmarks.md#telling-voices-apart).
- **Tiene giusti i tuoi nomi.** Un glossario corregge i nomi di clienti e prodotti dopo la trascrizione, e si può riapplicare alle call vecchie.
- **Resta sulla tua macchina.** Niente account, niente telemetria, niente LLM remoti. Ogni call è una cartella di file normali; riassunti ed email li scrive un modello che gira in locale.

## Avvio rapido

Un comando, niente da installare prima: porta il suo Python, non chiede i permessi di amministratore e sceglie il PyTorch che vede la tua GPU.

**Windows**, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/thetouchsite/sottovoce/main/installer/install.ps1 | iex
```

**Linux e macOS**, nel terminale:

```sh
curl -fsSL https://raw.githubusercontent.com/thetouchsite/sottovoce/main/installer/install.sh | bash
```

Poi apri **Sottovoce** dal menu Start o dal desktop. Su Windows è un programma a sé: una finestra, e un'icona vicino all'orologio dove continua a lavorare quando chiudi la finestra; **Esci**, nel menu dell'icona, lo spegne. Su Linux parte dal menu delle applicazioni, su Mac da `~/Applications`, e si apre nel browser. Le call stanno in una cartella `Sottovoce` nella tua cartella utente. Per aggiornare, rilancia lo stesso comando. È una GPU NVIDIA a renderlo veloce: senza, e su Mac, gira sulla CPU.

Il primo avvio scarica Whisper large-v3 (2,9 GB, una volta sola). Poi trascini una registrazione sulla pagina, scegli lingua e opzioni, e premi **Trascrivi**. Il pulsante **IT** in fondo alla barra laterale mette la pagina in italiano.

**Niente GPU sotto mano?** Sfoglia le quattro call inventate di `examples/`:

```sh
pip install -r requirements-dev.txt
python server.py --no-model --data examples/transcripts --glossary examples/glossary.txt
```

Installazione da un clone, aggiornamento, rimozione, riga di comando e API: [Getting started](docs/getting-started.md).

## Confronto

| | **Sottovoce** | [Meetily](https://github.com/Zackriya-Solutions/meetily) | [Vibe](https://github.com/thewh1teagle/vibe) | [noScribe](https://github.com/kaixxx/noScribe) | [Buzz](https://github.com/chidiwilliams/buzz) | [WhisperX](https://github.com/m-bain/whisperX) |
| --- | --- | --- | --- | --- | --- | --- |
| Registra le call | Microfono + audio di sistema su Windows, scheda del browser + microfono altrove, **su due tracce separate** | Microfono + audio di sistema | Microfono, audio di sistema, telefono | File | Microfono, dal vivo | File |
| Chi parla | Due tracce, o voci **senza account** | Edizione Pro, in arrivo | Sì | Sì (pyannote) | Sì | Sì (token Hugging Face) |
| Riassunti | **Solo locali**: modello incorporato, LM Studio, Ollama | Ollama o API cloud | Ollama o API Claude | – | Plugin | – |
| Mostra dove ricontrollare | **Striscia della call, rimozioni elencate** | – | – | – | – | – |
| Interfaccia | Pagina web, computer e telefono | App desktop | App desktop | App desktop | App desktop | Riga di comando, Python |
| GPU | NVIDIA | Apple, Vulkan; CUDA compilando | NVIDIA, AMD, Intel, Apple | NVIDIA, Apple Silicon | NVIDIA, Apple Silicon, Vulkan | NVIDIA |
| Installer | Script | Windows, macOS | Windows, macOS, Linux | Windows, macOS, Linux | Windows, macOS, Linux | pip |
| Licenza | MIT | MIT, Pro a pagamento | MIT | GPL-3.0 | MIT | BSD-2-Clause |

<sub>Dal README di ogni progetto al 23 ottobre 2026. Se qualcosa è cambiato, apri una issue e la tabella viene corretta.</sub>

Sottovoce è fatto per le call di lavoro: registrate prima o registrate qui, lette e corrette, archiviate col cliente. Se oggi ti servono qualsiasi GPU, un'app nativa su macOS o Linux o i sottotitoli dal vivo, Vibe e Buzz sono ottime scelte.

## Domande frequenti

**Esce qualcosa dal mio computer?**
No. Trascrizione, separazione delle voci e riassunti girano in locale, e la pagina non carica niente da internet. I modelli si scaricano una volta, al primo uso, da Hugging Face e GitHub. Vedi [SECURITY.md](SECURITY.md).

**Che GPU serve?**
Una scheda NVIDIA. Whisper large-v3 ci gira a mezza precisione; il modello incorporato per i riassunti chiede circa 8 GB in più, oppure si usano LM Studio od Ollama con un modello più piccolo. Senza GPU NVIDIA gira sul processore, molto più lento.

**Quali lingue?**
Whisper ne capisce molte e riconosce da solo la lingua. Sottovoce è misurato su italiano e inglese, e la sua pagina è in tutte e due.

**Posso usarlo nel rispetto del GDPR?**
Registrazioni, trascrizioni e riassunti non arrivano mai a terzi: nessun fornitore cloud, nessun trasferimento fuori dalla tua macchina. Il titolare resti tu, quindi restano tuoi i soliti obblighi: avvisare chi partecipa che viene registrato, avere una base giuridica, decidere per quanto tenere i file. Sono cartelle normali che puoi cancellare.

**Posso usarlo dal telefono?**
Sì, sul tuo Wi-Fi con `--lan` e un PIN: leggi, correggi, mandi registrazioni, condividi l'email di follow-up. Vedi [From your phone](docs/lan.md).

**Quanto è bravo?**
Sull'italiano pubblico ([FLEURS](docs/benchmarks.md#italian-read-speech)) sbaglia il 4,3% delle parole, quanto Whisper large-v3 da solo; su riunioni intere in inglese ([AMI](docs/benchmarks.md#english-meetings-whole)) il 25,4%, contro il 30,3%. Ogni cifra che pubblichiamo viene da uno script in `research/` che puoi rilanciare: [Benchmarks](docs/benchmarks.md). Quello che ancora non fa bene: [Limitations](docs/limitations.md).

## Documentazione

La documentazione è in inglese: [Getting started](docs/getting-started.md) · [How it works](docs/how-it-works.md) · [Recording a call](docs/recording.md) · [Telling voices apart](docs/voices.md) · [Summaries, notes and follow-ups](docs/summaries.md) · [The name glossary](docs/glossary.md) · [From your phone](docs/lan.md) · [Benchmarks](docs/benchmarks.md) · [Limitations](docs/limitations.md) · [Troubleshooting](docs/troubleshooting.md)

Anche sul web: **[thetouchsite.github.io/sottovoce](https://thetouchsite.github.io/sottovoce/)**.

## Per team e aziende

Sottovoce è sviluppato e mantenuto da **[TouchSite Software](https://www.touchsitesoftware.it)**. Per gli studi e le aziende che trattano call riservate (studi legali, commercialisti, sanità, risorse umane) lo installiamo sulle vostre macchine, costruiamo glossari per il vostro settore e i vostri clienti, lo colleghiamo agli strumenti che usate già, e lo seguiamo nel tempo.

**[info@touchsitesoftware.it](mailto:info@touchsitesoftware.it)**

## Contribuire

Issue e pull request sono benvenute: vedi [CONTRIBUTING.md](CONTRIBUTING.md) e la [roadmap](ROADMAP.md). I problemi di sicurezza vanno segnalati in privato, come spiegato in [SECURITY.md](SECURITY.md).

## Licenza

[MIT](LICENSE) © 2026 TouchSite Software. Le parti di terzi mantengono le loro licenze: Whisper large-v3 (Apache-2.0), Qwen3 4B Instruct (Apache-2.0), pyannote segmentation-3.0 (MIT), 3D-Speaker ERes2Net (Apache-2.0), sherpa-onnx (Apache-2.0), Public Sans (SIL OFL 1.1), ffmpeg (tramite `imageio-ffmpeg`, non incluso qui). I modelli si scaricano al primo uso e non sono inclusi nel repository.

*Sottovoce*: a bassa voce. Sono le frasi che cadono sotto il livello del parlato quelle che toglie, ed è così che lavora: in silenzio, sulla tua macchina.
