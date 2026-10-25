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

Trascini sulla pagina una call registrata, oppure registri la call da lì. Ottieni la trascrizione, chi ha detto cosa, un riassunto, gli appunti per la cartella del cliente, l'email di follow-up e una mappa dei punti da ricontrollare. Whisper large-v3 su una GPU NVIDIA o Intel, oppure sul solo processore. Niente esce dalla macchina.

## Perché Sottovoce

- **Ti mostra dove il testo è debole.** La *striscia della call* disegna tutta la registrazione in una banda: parlato, silenzio, frasi tolte, righe corrette. Clicchi in un punto e ascolti da lì.
- **Toglie quello che nessuno ha detto.** Sul silenzio Whisper scrive sottotitoli imparati da YouTube: *"Grazie per la visione"*. Sottovoce li toglie solo dove l'audio è molto sotto il parlato, ed elenca ogni rimozione. Su un test pubblico con pause lunghe aggiunge 47 parole che nessuno ha detto, dove Whisper da solo ne aggiunge 318 ([misurato](docs/benchmarks.md#long-pauses)).
- **Sa chi ha parlato.** Una call registrata qui tiene il tuo microfono e la call su due tracce, da qualsiasi app su Windows, da una scheda del browser altrove: *Tu* e *Loro* sono misurati, non indovinati. Su qualsiasi registrazione separa le voci senza account e senza token, con un [errore del 12% su riunioni pubbliche](docs/benchmarks.md#telling-voices-apart).
- **Tiene giusti i tuoi nomi.** Un glossario corregge i nomi di clienti e prodotti dopo la trascrizione, e si può riapplicare alle call vecchie.
- **Gira sul computer che hai.** Una scheda NVIDIA con PyTorch, una GPU Intel (Arc, o quella dentro il processore) o qualsiasi processore con OpenVINO, con la stessa precisione. Sceglie da solo il più veloce, e lo può misurare: sul portatile provato, la GPU Intel dentro il processore ha battuto la scheda RTX ([misurato](docs/benchmarks.md#where-it-runs)).
- **Resta sulla tua macchina.** Niente account, niente telemetria, niente LLM remoti. Ogni call è una cartella di file normali; riassunti ed email li scrive un modello che gira in locale: quello incorporato, o uno che hai già in LM Studio od Ollama, che Sottovoce accende e spegne da solo.

## Avvio rapido

**Windows:** scarica **Sottovoce-Setup-….exe** dall'[ultima release](https://github.com/thetouchsite/sottovoce/releases/latest) e aprilo. Non servono i permessi di amministratore. L'installazione non è ancora firmata, quindi Windows può dire che *ha protetto il PC*: **Ulteriori informazioni**, poi **Esegui comunque**.

Oppure con un comando, su ogni sistema: porta il suo Python, non chiede i permessi di amministratore e sceglie quello che fa girare Whisper più veloce sul tuo computer.

**Windows**, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/thetouchsite/sottovoce/main/installer/install.ps1 | iex
```

**Linux e macOS**, nel terminale:

```sh
curl -fsSL https://raw.githubusercontent.com/thetouchsite/sottovoce/main/installer/install.sh | bash
```

Poi apri **Sottovoce** dal menu Start o dal desktop. Su Windows è un programma a sé: una finestra, e un'icona vicino all'orologio dove continua a lavorare quando chiudi la finestra; **Esci**, nel menu dell'icona, lo spegne. Su Linux parte dal menu delle applicazioni, su Mac da `~/Applications`, e si apre nel browser. Le call stanno in una cartella `Sottovoce` nella tua cartella utente. Per aggiornare, apri la nuova installazione o rilancia lo stesso comando.

La prima trascrizione scarica Whisper large-v3, una volta sola, dopo averlo chiesto: 2,9 GB per una scheda NVIDIA, 1,5 GB per una GPU Intel o il processore. Poi trascini una registrazione sulla pagina, scegli lingua e opzioni, e premi **Trascrivi**. Il pulsante **IT** in fondo alla barra laterale mette la pagina in italiano.

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
| Riassunti | **Solo locali**: modello incorporato, o il tuo modello di LM Studio od Ollama, acceso per te | Ollama o API cloud | Ollama o API Claude | – | Plugin | – |
| Mostra dove ricontrollare | **Striscia della call, rimozioni elencate** | – | – | – | – | – |
| Interfaccia | Pagina web, computer e telefono | App desktop | App desktop | App desktop | App desktop | Riga di comando, Python |
| GPU | NVIDIA, Intel; qualsiasi processore x86 | Apple, Vulkan; CUDA compilando | NVIDIA, AMD, Intel, Apple | NVIDIA, Apple Silicon | NVIDIA, Apple Silicon, Vulkan | NVIDIA |
| Installer | Installazione per Windows; un comando su Windows, Linux, macOS | Windows, macOS | Windows, macOS, Linux | Windows, macOS, Linux | Windows, macOS, Linux | pip |
| Licenza | MIT | MIT, Pro a pagamento | MIT | GPL-3.0 | MIT | BSD-2-Clause |

<sub>Dal README di ogni progetto al 23 ottobre 2026. Se qualcosa è cambiato, apri una issue e la tabella viene corretta.</sub>

Sottovoce è fatto per le call di lavoro: registrate prima o registrate qui, lette e corrette, archiviate col cliente. Se oggi ti servono una GPU AMD o Apple, un'app nativa su macOS o Linux o i sottotitoli dal vivo, Vibe e Buzz sono ottime scelte.

## Domande frequenti

**Esce qualcosa dal mio computer?**
No. Trascrizione, separazione delle voci e riassunti girano in locale, e la pagina non carica niente da internet. I modelli si scaricano una volta, al primo uso, da Hugging Face e GitHub. Una volta al giorno Sottovoce chiede a GitHub se è uscita una versione nuova, e nient'altro; si può spegnere. Vedi [SECURITY.md](SECURITY.md).

**Che GPU serve?**
Nessuna è obbligatoria. Whisper large-v3 gira su una scheda NVIDIA (PyTorch), su una GPU Intel, Arc o dentro il processore, o sul solo processore, Intel o AMD (entrambi con OpenVINO), con la stessa precisione. Sul portatile misurato, un'ora di call ha richiesto circa 6 minuti sulla GPU Intel, 8 sulla scheda RTX e 12 sul processore ([dove gira](docs/benchmarks.md#where-it-runs)); un computer più piccolo è più lento, e la pagina mostra quanto ci mette sul tuo. Il modello incorporato per i riassunti chiede una scheda NVIDIA con circa 8 GB liberi; senza, scegli un modello che hai in LM Studio od Ollama.

**Quali lingue?**
Whisper ne capisce molte e riconosce da solo la lingua. Sottovoce è misurato su italiano e inglese, e la sua pagina è in tutte e due.

**Posso usarlo nel rispetto del GDPR?**
Registrazioni, trascrizioni e riassunti non arrivano mai a terzi: nessun fornitore cloud, nessun trasferimento fuori dalla tua macchina. Il titolare resti tu, quindi restano tuoi i soliti obblighi: avvisare chi partecipa che viene registrato, avere una base giuridica, decidere per quanto tenere i file. Sono cartelle normali che puoi cancellare.

**Posso usarlo dal telefono?**
Sì, sul tuo Wi-Fi con `--lan` e un PIN: leggi, correggi, mandi registrazioni, condividi l'email di follow-up. Vedi [From your phone](docs/lan.md).

**Quanto è bravo?**
Sull'italiano pubblico ([FLEURS](docs/benchmarks.md#italian-read-speech)) sbaglia il 4,3% delle parole, quanto Whisper large-v3 da solo; su riunioni intere in inglese ([AMI](docs/benchmarks.md#english-meetings-whole)) il 25,4%, contro il 30,3%. Su una GPU Intel o sul processore, con OpenVINO, lo stesso a pochi decimi ([dove gira](docs/benchmarks.md#where-it-runs)). Ogni cifra che pubblichiamo viene da uno script in `research/` che puoi rilanciare: [Benchmarks](docs/benchmarks.md). Quello che ancora non fa bene: [Limitations](docs/limitations.md).

## Documentazione

La documentazione è in inglese: [Getting started](docs/getting-started.md) · [How it works](docs/how-it-works.md) · [Recording a call](docs/recording.md) · [Telling voices apart](docs/voices.md) · [Summaries, notes and follow-ups](docs/summaries.md) · [The name glossary](docs/glossary.md) · [From your phone](docs/lan.md) · [Benchmarks](docs/benchmarks.md) · [Limitations](docs/limitations.md) · [Troubleshooting](docs/troubleshooting.md)

Anche sul web: **[thetouchsite.github.io/sottovoce](https://thetouchsite.github.io/sottovoce/)**.

## Per team e aziende

Sottovoce è sviluppato e mantenuto da **[TouchSite Software](https://www.touchsitesoftware.it)**. Per gli studi e le aziende che trattano call riservate (studi legali, commercialisti, sanità, risorse umane) lo installiamo sulle vostre macchine, costruiamo glossari per il vostro settore e i vostri clienti, lo colleghiamo agli strumenti che usate già, e lo seguiamo nel tempo.

**[info@touchsitesoftware.it](mailto:info@touchsitesoftware.it)**

## Contribuire

Issue e pull request sono benvenute: vedi [CONTRIBUTING.md](CONTRIBUTING.md) e la [roadmap](ROADMAP.md). I problemi di sicurezza vanno segnalati in privato, come spiegato in [SECURITY.md](SECURITY.md).

## Licenza

[MIT](LICENSE) © 2026 TouchSite Software. Le parti di terzi mantengono le loro licenze: Whisper large-v3 (Apache-2.0) e la sua conversione per OpenVINO (Apache-2.0), OpenVINO (Apache-2.0), Qwen3 4B Instruct (Apache-2.0), pyannote segmentation-3.0 (MIT), 3D-Speaker ERes2Net (Apache-2.0), sherpa-onnx (Apache-2.0), Public Sans (SIL OFL 1.1), ffmpeg (tramite `imageio-ffmpeg`, non incluso qui). I modelli si scaricano al primo uso e non sono inclusi nel repository.

*Sottovoce*: a bassa voce. Sono le frasi che cadono sotto il livello del parlato quelle che toglie, ed è così che lavora: in silenzio, sulla tua macchina.
