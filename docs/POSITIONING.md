# UGC Studio : positionnement, préparation à la publication, verdict LinkedIn

Document interne, rédigé le 26/09/2026 (tu peux le retirer du dépôt avant de le rendre public).

## 1. État réel du système aujourd'hui

| Brique | État | Preuve |
|---|---|---|
| Pipeline de génération (images, vidéo, voix, musique, montage, graphismes) | ✅ en production | 6 vidéos livrées : DZ-MeNU TV, Lina UGC ×2, promo 3D, promo arabe, spots Legal-Index |
| Contrôles qualité automatiques (mots, phonèmes, identité, prompt, qualité de voix) | ✅ | reprises automatiques observées en vrai (« dossiers », « jurisprudence », « banchaire ») |
| Réparations ciblées, cache incrémental | ✅ | tests + usage réel |
| Fournisseurs configurables (local ou cloud : Veo, Kling, Seedance, OpenAI, Gemini, ElevenLabs, HF) | ✅ code + tests d'API simulées | **pas encore appelés avec de vraies clés** |
| Voix-off modulaire, timeline éditable | ✅ | tests réels (analyse fréquentielle du mix) |
| API FastAPI + file de jobs Redis + worker GPU | ✅ | tests réels + Docker |
| Interface web Next.js (assistant, storyboard, rendu, correction, voix, timeline, exports) | ✅ | parcours Playwright complet contre la stack Docker |
| Docker Compose (redis, api, worker GPU, web) | ✅ | génération IA réelle sur GPU dans le conteneur |
| Tests | ✅ 90+ tests | modèles simulés + API cloud simulées + jobs réels |

## 2. Comparaison avec OpenMontage

[OpenMontage](https://github.com/calesthio/OpenMontage), licence AGPL-3.0 : environ 61 000 étoiles, créé en mars 2026, actif. Attention aux faux dépôts « Download OpenMontage » : ce sont des pièges à malware.

| | OpenMontage | UGC Studio (toi) |
|---|---|---|
| **Philosophie** | généraliste « agent-first » : ton assistant IA (Claude Code, Cursor…) *est* l'orchestrateur, avec plus de 700 fichiers de compétences | spécialiste déterministe : pipeline fixe, projet déclaratif, cache incrémental |
| **Types de vidéos** | 12 pipelines (explainer, documentaire, podcast, talking head, doublage…) | UGC / influenceur / faceless / pub produit et TV |
| **Fournisseurs** | plus de 60 (vidéo, image, voix, musique, banques d'images Pexels/Archive/NASA…) | local d'abord (LTX-2.5, FLUX.2, Qwen/Chatterbox/Habibi, ACE-Step), plus 7 fournisseurs cloud |
| **Montage** | Remotion ou HyperFrames + FFmpeg | moteur HTML/GSAP maison (même principe qu'HyperFrames), écrans réels incrustés sur téléphones IA, timeline éditable |
| **Contrôle qualité** | surtout structurel (ffprobe, frames noires, niveaux audio), validation humaine, budget | **automatique par modèles** : prononciation au phonème, identité DINOv2, prompt CLIP, meilleure prise par qualité de voix, reprise automatique |
| **Langues** | localisation « 10 langues », sous-titres CJK | **arabe, dialectes, RTL**, vérification de prononciation |
| **Matériel** | aucun GPU requis avec des clés cloud | pensé pour un GPU de 12 Go (cloud optionnel) |
| **Interface** | « Backlot » : storyboard live, validations, coûts | web app guidée « même un enfant » + CLI + API |
| **Communauté** | énorme | aucune (pour l'instant) |

**Où OpenMontage gagne :**
- l'étendue : pipelines, fournisseurs, banques d'images, recherche web ;
- la gouvernance des coûts ;
- la communauté.

**Où tu gagnes :**
- la profondeur sur un cas d'usage qui paie : pubs UGC et produit ;
- le contrôle qualité automatique mesurable ;
- l'insertion d'écrans réels ;
- les réparations chirurgicales ;
- le 100 % local sur un portable ;
- l'arabe et le RTL, qu'OpenMontage ne couvre pas.

**Autres projets à connaître :**
- [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) (~126k étoiles, MIT) : vidéo courte depuis un mot-clé.
- [HyperFrames](https://github.com/heygen-com/hyperframes) (~53k, Apache-2.0) : moteur HTML → vidéo.
- [Remotion](https://github.com/remotion-dev/remotion) (~60k, licence source-available payante au-delà de 3 employés).
- [LTX-Desktop](https://github.com/Lightricks/LTX-Desktop) (~2k).

## 3. Checklist avant publication

| Point | État |
|---|---|
| README avec démo GIF | ✅ `README.md` + `docs/media/demo.gif` (vrais rendus) |
| Vérification des licences | ✅ `docs/LICENSES.md` (voir les points bloquants ci-dessous) |
| Variables d'env pour choisir les modèles | ✅ `.env.example`, `ugc providers` |
| Docker « une commande » | ✅ `docker compose up -d --build` |
| Docs utilisateur et architecture | ✅ `GUIDE.md`, `ARCHITECTURE.md`, OpenAPI |
| **Choisir la licence de TON code** | ❌ à décider : Apache-2.0 (brevets, adoption entreprise) ou MIT (simple). À éviter : AGPL si tu veux une adoption large. |
| Nettoyer le dépôt | ⚠️ à faire : `todo.md` (notes perso), `projects/dzmenu/` (ancien pipeline), ce fichier |
| Marques clientes dans la démo | ⚠️ DZ-MeNU et Legal-Index sont tes produits : OK. N'y mets jamais de marque tierce. |
| Premier appel réel des fournisseurs cloud | ⚠️ testés contre des API simulées fidèles aux docs officielles, pas encore avec une vraie clé |

### Points de licence qui te concernent directement

1. **LTX-2.5 (vidéo locale) :**
   - gratuit si ton entreprise fait moins de 10 M$ de chiffre d'affaires ;
   - **mention « contenu généré par IA » obligatoire** sur les vidéos publiées ;
   - pas de faux témoignages présentés comme réels ;
   - une clause interdit un produit qui *concurrence* LTX Studio : **si tu vends un service hébergé de génération vidéo, demande une confirmation écrite à Lightricks.**
2. **Habibi (voix darija de tes spots Legal-Index) :** son usage commercial est **incertain**, car le modèle est entraîné à partir d'une base non commerciale (F5-TTS / Emilia). Pour la diffusion TV, deux options : obtenir une confirmation écrite des auteurs, ou refaire la voix avec Chatterbox (arabe standard, licence MIT), une voix cloud (ElevenLabs gère l'arabe) ou un vrai comédien. Le système avertit désormais à chaque usage.
3. **Qualité de voix :** le modèle SQUIM « MOS » était non commercial. Il est remplacé par SQUIM objectif (CC-BY-4.0).
4. **Image Docker publiée :** elle contient des composants GPL (espeak-ng, FFmpeg). Si tu la distribues, elle doit l'être en GPL-3 avec les sources. Ton code source seul peut rester sous licence permissive.

## 4. Verdict LinkedIn, en toute honnêteté

**Oui, ça vaut la peine de le publier, et maintenant, à condition de le présenter pour ce que c'est.**

**Pourquoi c'est crédible :**
- **Des résultats réels :** des spots terminés (TV 30/60 s, UGC, arabe darija). La plupart des projets « IA vidéo » sur LinkedIn ne montrent que des démos de 5 secondes.
- **Un vrai problème résolu :** la plupart des outils génèrent et espèrent que ça passe. Le tien *vérifie* (prononciation au phonème, identité, qualité) et *répare* seulement ce qui est cassé. C'est un vrai différenciateur technique, et il se raconte bien (l'histoire de « banchaire » est parfaite).
- **Un système complet :** 100 % local sur un portable, open source, avec CLI + API + web app + Docker, arabe et RTL. C'est rare, et c'est pertinent pour le marché algérien et MENA.

**Ce qu'il ne faut pas prétendre :**
- Pas « au niveau de Runway, HeyGen ou Google ». Ce n'est pas vrai sur la vitesse (30 à 60 min pour 30 s en local), l'échelle, ni le polish de certaines voix.
- Pas « prêt pour la production commerciale sans réserve », à cause des points de licence ci-dessus.
- Pas « meilleur qu'OpenMontage » : c'est un autre positionnement (spécialiste contre généraliste).

**Ce qui manque pour passer de « projet impressionnant » à « produit » :**
- la communauté et une démo en ligne ;
- l'authentification et le multi-utilisateur sur l'API ;
- un premier vrai client via les fournisseurs cloud (vitesse) ;
- une voix darija de comédien (qualité perçue).

**Angle recommandé :** « J'ai construit un studio vidéo IA open source qui tourne sur un portable et qui vérifie lui-même son travail : prononciation, visages, qualité. Il refait seulement ce qui est raté. »

### Brouillon de post (FR)

> J'ai construit un studio de production vidéo IA open source… qui tourne sur mon portable.
>
> Pubs UGC, spots TV, vidéos en darija : du brief à la vidéo finale, en local, sur une carte graphique de 12 Go.
>
> Le problème de la vidéo IA aujourd'hui, ce n'est pas de générer : c'est de savoir si c'est bon.
> Alors le studio vérifie tout, seul :
> 🎙 la prononciation, phonème par phonème (Whisper entend « bancaire » même quand l'acteur dit « banchaire » ; mon système, non) ;
> 🧑 que le visage reste le même d'un plan à l'autre ;
> 🔁 et il refait uniquement ce qui est raté, pas toute la vidéo.
>
> + l'écran réel de l'application incrusté sur le téléphone filmé par l'IA
> + l'arabe et les dialectes, de droite à gauche
> + une interface web, une API, Docker, et des modèles cloud (Veo, Kling, ElevenLabs…) en option
>
> Démo 👇 · Code : [lien]
> #IA #OpenSource #VideoIA #Algérie

Publie avec le GIF ou une vidéo de 30 s (le spot Legal-Index 30 s ou la promo arabe DZ-MeNU), et la mention « contenu généré par IA ».
