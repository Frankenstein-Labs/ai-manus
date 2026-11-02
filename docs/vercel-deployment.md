# Déploiement Vercel — guide et état de validation

Le dépôt conserve deux services Vercel : l’interface Vue et l’API FastAPI. `vercel.json` envoie `/api/*` au backend et le reste au frontend. Le fournisseur de sandbox demeure Docker par défaut pour Docker Compose local. Le nouveau fournisseur `SANDBOX_PROVIDER=vercel` sélectionne le SDK officiel Vercel Sandbox et l’adaptateur du dépôt; il nécessite une image Sandbox disponible dans le Vercel Container Registry.

## État : prêt pour des essais contrôlés, pas encore certifié pour la production

Le dépôt a maintenant un adaptateur Vercel Sandbox, un relais CDP authentifié sur l’API du sandbox, un accès API sandbox par Bearer token et un accès VNC par token Websockify. Chrome écoute CDP sur loopback; les ports CDP/RFB bruts ne sont plus déclarés dans l’image. Ces changements ont fait l’objet d’une validation de code et des tests/builds indiqués dans le rapport de travail, mais ils ne peuvent pas être considérés comme une intégration Vercel réellement validée sans credentials de projet, image publiée dans Vercel Container Registry et déploiement de prévisualisation.

**Ne pas annoncer un déploiement fonctionnel avant d’avoir exécuté le parcours complet dans Vercel.** Il reste à vérifier l’authentification du SDK dans le service backend, la création/reprise/destruction d’un sandbox, la disponibilité des routes publiques exposées, les tunnels WebSocket VNC/CDP à travers Vercel, ainsi que les tâches agent après une reconnexion ou un redémarrage. Vercel Sandbox a une durée d’exécution bornée : un sandbox n’est pas un daemon Docker permanent.

Le mode de tâches par défaut `TASK_BACKEND=local` garde les tâches dans la mémoire d’un processus. Il ne fournit pas la reprise inter-instance nécessaire à une API serverless. Une configuration Celery nécessite un worker durable effectivement déployé et testé; le présent `vercel.json` ne le déclare pas. Tant que cette architecture de tâches longues et sa reprise ne sont pas validées, ce dépôt ne doit pas être présenté comme un service agent de production fiable.

L’authentification par mot de passe conserve son format historique de hash avec sel global et faible coût par défaut. Les sessions Redis sont révoquées au changement/réinitialisation du mot de passe, mais aucun migration de hash ni OAuth GitHub n’est fourni. Prévoir une migration des comptes et un audit dédié avant un lancement public.

## Services externes requis

- **Vercel Services** : déploiement des conteneurs frontend et backend et routage HTTP/WebSocket.
- **Vercel Sandbox + Vercel Container Registry** : exécution isolée des sandboxes et image runtime publiée. La configuration d’identité/permissions Vercel doit autoriser le SDK à créer et gérer des sandboxes depuis le service backend.
- **MongoDB compatible MongoDB** : stockage des utilisateurs, sessions et données applicatives (par exemple MongoDB Atlas).
- **Redis compatible Redis** : sessions d’authentification, état/évènements et broker si l’architecture de tâches distribuées est retenue (par exemple un fournisseur via Marketplace, avec `rediss://` recommandé lorsque disponible).
- **Fournisseur LLM** : endpoint OpenAI-compatible ou fournisseur supporté par le projet et sa clé API.

La présence d’une intégration Marketplace ne signifie pas que la base de données est hébergée par Vercel; les ressources sont opérées par le fournisseur externe.

## Variables d’environnement backend

Configurer les valeurs comme secrets côté serveur Vercel, jamais comme variables frontend `VITE_*` :

| Variable | Valeur / usage |
| --- | --- |
| `APP_ENV` | `production`; active les contrôles de configuration de production. |
| `API_KEY` | Clé privée du fournisseur LLM (ou clé passée au gateway configuré). |
| `MONGODB_URI` | URI TLS/connexion de la base MongoDB. |
| `MONGODB_DATABASE` | Nom de la base, généralement `manus`. |
| `REDIS_URL` | URI Redis, `rediss://` si TLS est disponible. |
| `AUTH_PROVIDER` | `password` pour l’authentification par mot de passe; ne pas utiliser `none`. |
| `JWT_SECRET_KEY` | Secret aléatoire unique d’au moins 32 caractères; le placeholder d’exemple est refusé en production. |
| `PASSWORD_SALT` | Sel historique requis par le hash actuel; planifier sa migration, ne pas réutiliser entre environnements. |
| `SESSION_COOKIE_SECURE` | `true` derrière HTTPS. |
| `CORS_ALLOWED_ORIGINS` | Liste CSV exacte des origines frontales de confiance, par exemple `https://app.example.com`; obligatoire en production. |
| `SANDBOX_PROVIDER` | `vercel` pour la Sandbox Vercel; omis ou `docker` pour le mode Docker local. |
| `VERCEL_SANDBOX_IMAGE` | Référence exacte d’une image runtime publiée et accessible dans le Container Registry du projet Vercel. |
| `SANDBOX_ACCESS_TOKEN` | Secret aléatoire d’au moins 32 caractères injecté dans le sandbox; protège son API/CDP et sert de jeton VNC. |
| `SANDBOX_TTL_MINUTES` | Durée d’exécution demandée, plafonnée à 45 minutes par l’adaptateur; tester le comportement après expiration. |
| `BROWSER_ENGINE` | Facultatif : `browser_use` ou `playwright`. |
| `TASK_BACKEND` | `local` par défaut; `celery` seulement si un broker et un worker durable séparé sont déployés et validés. |

Selon la configuration du projet Vercel et du SDK, l’identité d’exécution doit aussi fournir les credentials/OIDC nécessaires à Vercel Sandbox. Ne pas remplacer ce contrôle d’accès par un token écrit dans le frontend.

## Vérifications nécessaires avant mise en production

1. Construire les images `backend/Dockerfile.vercel`, `frontend/Dockerfile.vercel` et l’image runtime sous `sandbox/`, avec les fichiers `uv.lock` correspondants.
2. Depuis une Preview Vercel, confirmer le démarrage de l’API et du frontend, puis vérifier `/api/v1/config/frontend` et les probes de santé disponibles.
3. Créer une session et une tâche agent; confirmer que le sandbox démarre, exécute des commandes et fichiers, charge Chrome, puis qu’il est détruit à la fin.
4. Vérifier qu’une requête sans Bearer est refusée sur les routes sandbox et CDP; vérifier le refus du jeton incorrect sur VNC; tester les handshakes WebSocket d’origines étrangères sur chat, sessions et VNC.
5. Maintenir un viewer VNC, tester les outils navigateur/CDP, interrompre le réseau, vérifier la reconnexion VNC et le rattrapage des évènements chat après reconnexion.
6. Laisser une tâche dépasser la durée autorisée d’une Function et une durée de vie Sandbox; vérifier son état, son annulation et sa reprise depuis un autre processus.
7. Déployer un worker Celery durable ou adopter un service de tâches durable testé avant d’ouvrir le service à des utilisateurs.

`docker` n’est pas requis dans un Vercel Function : l’adaptateur passe par le SDK Vercel Sandbox. Il reste requis en développement local pour le fournisseur Docker. Un build de conteneur ou un test unitaire local ne remplace pas les essais Preview qui nécessitent les credentials et ressources Vercel réels.
