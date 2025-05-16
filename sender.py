#!/usr/bin/env python3
import os
import csv
import sys
import re
import smtplib
import requests
from bs4 import BeautifulSoup
import time
import tempfile
from fpdf import FPDF
from urllib.parse import urljoin, urlparse
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import random
import logging
from datetime import datetime
import json
import dotenv
import argparse
import backoff  # Add backoff for rate limiting

# Charger les variables d'environnement depuis le fichier .env
dotenv.load_dotenv(override=True)

# Configuration du logging par défaut
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Définition des valeurs par défaut (remplacées par les variables d'environnement si définies)
NOM_CANDIDAT = os.getenv('NOM_CANDIDAT', "Votre Nom")

# Fix for multiline SIGNATURE issue
default_signature = """

Cordialement,
Votre Nom
Tél: Votre numéro
Email: votre@email.com
"""

# Read the .env file directly for multi-line values if needed
SIGNATURE = os.getenv('SIGNATURE', default_signature)
if not SIGNATURE or len(SIGNATURE) < 10:
    try:
        with open('.env', 'r') as env_file:
            sig_start = False
            signature_lines = []
            for line in env_file:
                if 'SIGNATURE=' in line:
                    sig_start = True
                    # Get anything after the = on this line
                    first_part = line.split('SIGNATURE=', 1)[1].strip()
                    if first_part:
                        signature_lines.append(first_part)
                elif sig_start and line.strip() and not line.strip().startswith('#') and not '=' in line:
                    signature_lines.append(line.strip())
                elif sig_start and ('=' in line or line.strip().startswith('#')):
                    sig_start = False
            
            if signature_lines:
                SIGNATURE = '\n'.join(signature_lines)
    except Exception as e:
        logging.warning(f"Could not parse SIGNATURE from .env file: {e}")
        SIGNATURE = default_signature

# Other environment variables  
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY', "")  # À définir dans .env

# Trouver le chemin du CV
script_dir = os.path.dirname(os.path.abspath(__file__))
CHEMIN_CV = os.getenv('CHEMIN_CV', os.path.join(script_dir, "votre_cv.pdf"))
CHEMIN_OUTPUT = os.getenv('CHEMIN_OUTPUT', os.path.join(script_dir, "output"))
CHEMIN_LOGS = os.getenv('CHEMIN_LOGS', os.path.join(script_dir, "logs"))
CHEMIN_SUIVI = os.getenv('CHEMIN_SUIVI', os.path.join(script_dir, "emails_envoyes.csv"))

# Créer les répertoires s'ils n'existent pas
for directory in [CHEMIN_OUTPUT, CHEMIN_LOGS]:
    if not os.path.exists(directory):
        os.makedirs(directory)

# Configuration pour le crawler
CRAWLER_CONFIG = {
    'max_depth': int(os.getenv('CRAWLER_MAX_DEPTH', 3)),
    'max_pages': int(os.getenv('CRAWLER_MAX_PAGES', 20)),
    'delay': float(os.getenv('CRAWLER_DELAY', 1.0)),
    'timeout': int(os.getenv('CRAWLER_TIMEOUT', 10)),
    'user_agent': os.getenv('CRAWLER_USER_AGENT', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.93 Safari/537.36')
}

# Configuration pour l'envoi d'email
EMAIL_CONFIG = {
    'smtp_server': os.getenv('EMAIL_SMTP_SERVER', 'smtp.gmail.com'),
    'smtp_port': int(os.getenv('EMAIL_SMTP_PORT', 587)),
    'delay_min': int(os.getenv('EMAIL_DELAY_MIN', 5)),  # délai minimum entre deux emails en secondes
    'delay_max': int(os.getenv('EMAIL_DELAY_MAX', 15))  # délai maximum entre deux emails en secondes
}

# API Configuration with rate limiting
API_CONFIG = {
    'max_retries': int(os.getenv('API_MAX_RETRIES', 5)),
    'backoff_factor': float(os.getenv('API_BACKOFF_FACTOR', 2.0)),
    'rate_limit_pause': float(os.getenv('API_RATE_LIMIT_PAUSE', 60.0)),
    'request_timeout': int(os.getenv('API_REQUEST_TIMEOUT', 30))
}

# Variantes d'introduction pour les emails
EMAIL_INTROS = [
    """
    <p>Bonjour,</p>

    <p>
      J'ai découvert avec intérêt le travail de <strong>{nom_entreprise}</strong> dans le domaine {categorie} et je me permets de vous contacter au sujet d'une opportunité de stage.
    </p>
    """,
    """
    <p>Bonjour,</p>

    <p>
      Votre expertise en {categorie} m'a particulièrement impressionné, et c'est pourquoi je souhaite proposer ma candidature à <strong>{nom_entreprise}</strong> pour un stage en développement.
    </p>
    """,
    """
    <p>Bonjour,</p>

    <p>
      Suite à mes recherches sur les entreprises innovantes en {categorie}, <strong>{nom_entreprise}</strong> a retenu toute mon attention, et je souhaiterais contribuer à vos projets dans le cadre d'un stage.
    </p>
    """
]

def crawler_site_entreprise(url):
    """
    Crawle le site web d'une entreprise pour extraire des informations pertinentes
    comme la description, les valeurs, les projets et les domaines d'expertise.
    """
    if not url or not url.startswith(('http://', 'https://')):
        return {"description": "", "valeurs": [], "expertises": [], "projets": []}
    
    # Normaliser l'URL
    parsed_url = urlparse(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    
    # Pages cibles à analyser
    target_pages = {
        "about": ["a-propos", "qui-sommes-nous", "about", "entreprise", "presentation", "societe"],
        "values": ["valeurs", "values", "notre-mission", "mission", "vision", "philosophie"],
        "expertise": ["expertise", "competences", "services", "solutions", "offres", "savoir-faire"],
        "projects": ["projets", "realisations", "portfolio", "references", "clients"]
    }
    
    results = {
        "description": "",
        "valeurs": [],
        "expertises": [],
        "projets": []
    }
    
    visited_urls = set()
    current_depth_urls = {base_url}
    next_depth_urls = set()
    depth = 0
    
    try:
        while current_depth_urls and depth < CRAWLER_CONFIG['max_depth'] and len(visited_urls) < CRAWLER_CONFIG['max_pages']:
            for current_url in current_depth_urls:
                if current_url in visited_urls:
                    continue
                    
                visited_urls.add(current_url)
                
                try:
                    # Ajout d'un délai pour éviter de surcharger le serveur
                    time.sleep(CRAWLER_CONFIG['delay'])
                    response = requests.get(
                        current_url,
                        headers={'User-Agent': CRAWLER_CONFIG['user_agent']},
                        timeout=CRAWLER_CONFIG['timeout']
                    )
                    
                    if response.status_code != 200:
                        continue
                        
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Extraire le texte principal en excluant les éléments de navigation, en-tête, etc.
                    for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'meta']):
                        tag.decompose()
                    
                    # Analyser la page pour déterminer son type
                    page_type = None
                    page_path = urlparse(current_url).path.lower()
                    
                    for type_name, keywords in target_pages.items():
                        if any(keyword in page_path for keyword in keywords):
                            page_type = type_name
                            break
                    
                    # Extraire le contenu en fonction du type de page
                    if page_type == "about" or current_url == base_url:
                        main_content = soup.find('main') or soup.find('div', class_=re.compile(r'content|main|body'))
                        
                        if main_content:
                            paragraphs = main_content.find_all('p')
                        else:
                            paragraphs = soup.find_all('p')
                        
                        for p in paragraphs:
                            text = p.get_text(strip=True)
                            if len(text) > 100 and any(keyword in text.lower() for keyword in ['entreprise', 'société', 'nous', 'expert', 'spécialisé', 'créé']):
                                if len(results["description"]) < len(text):
                                    results["description"] = text
                    
                    elif page_type == "values":
                        values_lists = soup.find_all(['ul', 'ol'])
                        for vlist in values_lists:
                            items = vlist.find_all('li')
                            for item in items:
                                value_text = item.get_text(strip=True)
                                if 10 < len(value_text) < 100:
                                    results["valeurs"].append(value_text)
                    
                    elif page_type == "expertise":
                        headings = soup.find_all(['h2', 'h3', 'h4'])
                        for heading in headings:
                            expertise_text = heading.get_text(strip=True)
                            if 5 < len(expertise_text) < 50:
                                results["expertises"].append(expertise_text)
                                
                        service_lists = soup.find_all(['ul', 'ol'])
                        for slist in service_lists:
                            items = slist.find_all('li')
                            for item in items:
                                service_text = item.get_text(strip=True)
                                if 5 < len(service_text) < 100:
                                    results["expertises"].append(service_text)
                    
                    elif page_type == "projects":
                        project_elements = soup.find_all(['h3', 'h4', 'div'], class_=re.compile(r'project|client|reference'))
                        for element in project_elements:
                            project_text = element.get_text(strip=True)
                            if project_text and 5 < len(project_text) < 100:
                                results["projets"].append(project_text)
                    
                    if current_url == base_url and not results["description"]:
                        title_tag = soup.find('title')
                        meta_desc = soup.find('meta', attrs={'name': 'description'})
                        
                        if title_tag:
                            title = title_tag.get_text(strip=True)
                            if title and len(title) > 10:
                                results["description"] = f"Entreprise: {title}. "
                        
                        if meta_desc and meta_desc.get('content'):
                            meta_content = meta_desc.get('content', '')
                            if len(meta_content) > 20:
                                results["description"] += meta_content
                    
                    if depth < CRAWLER_CONFIG['max_depth'] - 1:
                        links = soup.find_all('a', href=True)
                        for link in links:
                            href = link['href']
                            if href.startswith('/') or (href.startswith(base_url) and not href.startswith('#')):
                                full_url = urljoin(base_url, href)
                                if urlparse(full_url).netloc == parsed_url.netloc and full_url not in visited_urls:
                                    for keywords in target_pages.values():
                                        if any(keyword in full_url.lower() for keyword in keywords):
                                            next_depth_urls.add(full_url)
                                            break
                
                except (requests.RequestException, Exception) as e:
                    logging.error(f"Erreur lors du crawling de {current_url}: {e}")
                    continue
            
            current_depth_urls = next_depth_urls
            next_depth_urls = set()
            depth += 1
        
        results["valeurs"] = list(set(results["valeurs"]))[:5]
        results["expertises"] = list(set(results["expertises"]))[:5]
        results["projets"] = list(set(results["projets"]))[:3]
        
        return results
    
    except Exception as e:
        logging.error(f"Erreur générale lors du crawling de {url}: {e}")
        return {"description": "", "valeurs": [], "expertises": [], "projets": []}

def nettoyer_contenu_genere(texte, nom_entreprise):
    """
    Nettoie le contenu généré par l'IA pour en faire une lettre de motivation professionnelle.
    """
    # Supprimer tout ce qui précède "Madame", "Monsieur", etc.
    texte = re.sub(r'^.*?(?=Cher|Bonjour|Madame|Monsieur)', '', texte, flags=re.DOTALL)
    
    # Supprimer les mentions d'objet
    texte = re.sub(r'Objet\s*:\s*.*?\n', '', texte)
    
    # Remplacer les placeholders génériques
    texte = texte.replace("[Votre nom]", "").replace("[Nom]", "")
    texte = texte.replace("étudiant(e)", "étudiant").replace("candidat(e)", "candidat")
    texte = texte.replace("[votre domaine]", "développement informatique")
    texte = texte.replace("[compétence spécifique]", "développement web moderne")
    
    # Supprimer les espaces multiples
    texte = re.sub(r'\n\s*\n\s*\n+', '\n\n', texte)
    
    # Corriger les problèmes d'encodage courants
    texte = texte.replace("?uvre", "œuvre")
    texte = texte.replace("?", "'")
    
    # Assurer que la signature est correcte
    if "Cordialement" not in texte:
        texte = texte.rstrip() + SIGNATURE
    else:
        texte = re.sub(r'Cordialement,?\s*(\[.*?\])?$', SIGNATURE.lstrip(), texte)
    
    return texte.strip()

def creer_lettre_motivation_pdf(contenu, nom_entreprise):
    """
    Crée un fichier PDF à partir du contenu de la lettre de motivation.
    """
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=11)
        
        for line in contenu.split('\n'):
            if not line.strip():
                pdf.ln(5)
            else:
                pdf.multi_cell(0, 5, line.encode('latin-1', 'replace').decode('latin-1'))
        
        fd, temp_path = tempfile.mkstemp(suffix='.pdf', prefix=f'LM_{nom_entreprise.replace(" ", "_")}_')
        os.close(fd)
        
        pdf.output(temp_path)
        return temp_path
    except Exception as e:
        logging.error(f"Erreur lors de la création du PDF de la lettre de motivation: {e}")
        return None

def generer_lettre_motivation(entreprise_info):
    """
    Génère le contenu de la lettre de motivation en utilisant l'API Mistral.
    """
    try:
        nom_entreprise = entreprise_info.get('title', 'votre entreprise')
        categorie = entreprise_info.get('category', 'entreprise')
        ville = entreprise_info.get('city', '')
        website = entreprise_info.get('website', '')
        
        site_info = {"description": "", "valeurs": [], "expertises": [], "projets": []}
        if website:
            logging.info(f"Crawling du site {website}...")
            site_info = crawler_site_entreprise(website)
            logging.info("Crawling terminé.")
        
        description = site_info["description"]
        valeurs = ", ".join(site_info["valeurs"]) if site_info["valeurs"] else ""
        expertises = ", ".join(site_info["expertises"]) if site_info["expertises"] else ""
        projets = ", ".join(site_info["projets"]) if site_info["projets"] else ""
        
        info_supplementaire = ""
        if description:
            info_supplementaire += f"\nDescription de l'entreprise: {description}\n"
        if valeurs:
            info_supplementaire += f"\nValeurs de l'entreprise: {valeurs}\n"
        if expertises:
            info_supplementaire += f"\nDomaines d'expertise: {expertises}\n"
        if projets:
            info_supplementaire += f"\nProjets/clients notables: {projets}\n"
        
        # Amélioration du prompt pour générer un contenu plus spécifique
        prompt = f"""
        Écris une lettre de motivation personnalisée et spécifique pour un stage en développement informatique chez {nom_entreprise},
        qui est une entreprise du secteur {categorie} située à {ville}.
        
        {info_supplementaire}
        
        Consignes très importantes:
        - La lettre est pour un candidat masculin nommé Elijah Lasserre, 22 ans
        - Commence directement par "Madame, Monsieur," sans aucun texte d'introduction 
        - NE PAS utiliser de placeholders comme [votre domaine] ou [compétence spécifique]
        - Mentionne spécifiquement l'entreprise {nom_entreprise} et ses activités
        - Fais référence à des compétences précises: HTML, CSS, TypeScript, React, Java et cybersécurité
        - Mentionne mon expérience de stage précédente en développement web chez S2E Groupe
        - Évite les formules trop génériques ou qui pourraient s'appliquer à n'importe quelle entreprise
        - Adapte le contenu spécifiquement à l'activité de {nom_entreprise} et son secteur ({categorie})
        - La lettre doit être professionnelle mais pas trop formelle
        - N'utilise pas la signature à la fin, elle sera ajoutée automatiquement
        """
        
        # Appel à l'API Mistral avec gestion des rate limits
        url = "https://api.mistral.ai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {MISTRAL_API_KEY}"
        }
        
        data = {
            "model": "mistral-large-latest",
            "messages": [
                {"role": "system", "content": "Tu es un expert en rédaction de lettres de motivation professionnelles, claires et personnalisées."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 1024
        }
        
        max_retries = API_CONFIG['max_retries']
        backoff_factor = API_CONFIG['backoff_factor']
        
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    url, 
                    headers=headers, 
                    json=data,
                    timeout=API_CONFIG['request_timeout']
                )
                
                if response.status_code == 200:
                    result = response.json()
                    texte = result["choices"][0]["message"]["content"]
                    texte_nettoye = nettoyer_contenu_genere(texte, nom_entreprise)
                    return texte_nettoye
                    
                elif response.status_code == 429:  # Rate limit error
                    wait_time = API_CONFIG['rate_limit_pause'] * (backoff_factor ** attempt)
                    logging.warning(f"Rate limit atteint. Attente de {wait_time:.1f} secondes avant nouvelle tentative ({attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                    
                else:
                    response.raise_for_status()  # Will raise an exception for 4xx/5xx
                    
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    wait_time = API_CONFIG['rate_limit_pause'] * (backoff_factor ** attempt)
                    logging.warning(f"Erreur lors de l'appel API: {e}. Nouvelle tentative dans {wait_time:.1f} secondes ({attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    logging.error(f"Toutes les tentatives d'appel à l'API ont échoué: {e}")
                    raise
        
        # Si toutes les tentatives échouent, utiliser le contenu de secours
        raise Exception("Échec de toutes les tentatives d'appel à l'API Mistral")
    
    except Exception as e:
        logging.error(f"Erreur lors de la génération du contenu avec Mistral API: {e}")
        # Fallback en cas d'erreur
        nom_entreprise = entreprise_info.get('title', 'votre entreprise')
        return f"""Madame, Monsieur,

Je me permets de vous adresser ma candidature pour un stage en développement informatique au sein de {nom_entreprise}.

Actuellement en formation de Concepteur Développeur d'Applications, je suis à la recherche d'une opportunité de stage de 4 mois (du 10 septembre 2024 au 9 janvier 2025) pour mettre en pratique mes compétences en programmation et contribuer à des projets concrets. Votre entreprise m'intéresse particulièrement pour son expertise dans le domaine {entreprise_info.get('category', 'technologique')}.

Au cours de ma formation et de mon précédent stage chez S2E Groupe, j'ai acquis des compétences solides en développement web (HTML, CSS, JavaScript, TypeScript, React) ainsi qu'en programmation Java et en cybersécurité. Cette expérience m'a permis de développer ma capacité à résoudre des problèmes complexes et à m'adapter rapidement à différents environnements techniques.

Je suis convaincu que mon profil correspondrait aux attentes de votre entreprise et je serais ravi de pouvoir échanger avec vous lors d'un entretien pour vous présenter plus en détail mon parcours et mes motivations.

Vous trouverez en pièce jointe mon CV détaillant mon parcours et mes compétences.

"""

def verifier_email_deja_envoye(email, nom_entreprise):
    """
    Vérifie si un email a déjà été envoyé à l'entreprise spécifiée.
    Retourne True si l'email a déjà été envoyé, False sinon.
    """
    if not os.path.exists(CHEMIN_SUIVI):
        # Créer le fichier s'il n'existe pas
        with open(CHEMIN_SUIVI, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['email', 'nom_entreprise', 'date_envoi'])
        return False
    
    try:
        with open(CHEMIN_SUIVI, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['email'].lower() == email.lower() or row['nom_entreprise'].lower() == nom_entreprise.lower():
                    return True
        return False
    except Exception as e:
        logging.error(f"Erreur lors de la vérification des emails déjà envoyés: {e}")
        return False

def enregistrer_email_envoye(email, nom_entreprise):
    """
    Enregistre dans le fichier de suivi qu'un email a été envoyé à l'entreprise spécifiée.
    """
    try:
        fichier_existe = os.path.exists(CHEMIN_SUIVI)
        
        with open(CHEMIN_SUIVI, 'a', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            if not fichier_existe:
                writer.writerow(['email', 'nom_entreprise', 'date_envoi'])
            
            writer.writerow([email, nom_entreprise, datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
        
        logging.info(f"Suivi: Email envoyé à {nom_entreprise} ({email}) enregistré")
        return True
    except Exception as e:
        logging.error(f"Erreur lors de l'enregistrement du suivi d'email: {e}")
        return False

def envoyer_email_avec_cv(destinataire, objet, contenu, expediteur, mot_de_passe,
                          chemin_cv=CHEMIN_CV, nom_entreprise="", serveur_smtp=EMAIL_CONFIG['smtp_server'], 
                          port=EMAIL_CONFIG['smtp_port'], entreprise_info=None):
    """
    Envoie un email via SMTP avec la lettre de motivation et le CV en pièce jointe.
    """
    temp_pdf_path = None
    
    try:
        msg = MIMEMultipart()
        msg['From'] = expediteur
        msg['To'] = destinataire
        msg['Subject'] = objet
        msg['Reply-To'] = expediteur
        
        # Choisir une introduction au hasard
        intro_template = random.choice(EMAIL_INTROS)
        
        # Utiliser la catégorie si disponible, sinon 'technologie' par défaut
        categorie = 'technologie'
        if entreprise_info and 'category' in entreprise_info:
            categorie = entreprise_info['category']
        
        intro_html = intro_template.format(nom_entreprise=nom_entreprise, categorie=categorie)
        
        # HTML content for the email body
        html_content = f"""
        <!DOCTYPE html>
        <html lang="fr">
          <head>
            <meta charset="UTF-8" />
            <title>Candidature Stage - Elijah Lasserre</title>
            <style>
              body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                background-color: #fff;
                padding: 20px;
                max-width: 600px;
              }}
              p {{
                margin-bottom: 14px;
              }}
              .highlight {{
                color: #1a73e8;
              }}
              a {{
                color: #1a73e8;
                text-decoration: none;
                font-weight: 500;
              }}
              a:hover {{
                text-decoration: underline;
              }}
              .signature {{
                margin-top: 20px;
                border-top: 1px solid #eee;
                padding-top: 10px;
              }}
            </style>
          </head>
          <body>
            {intro_html}

            <p>
              Je suis <strong>Elijah Lasserre</strong>, en formation <strong>Concepteur Développeur d'Applications</strong>,
              et je recherche un <strong>stage de 4 mois</strong> (du 10 septembre 2024 au 9 janvier 2025) qui me permettrait
              de contribuer à des projets concrets tout en développant mes compétences.
            </p>

            <p>
              <strong>Ce que je peux apporter à votre équipe :</strong>
              <ul>
                <li>Solides compétences techniques en <strong>HTML, CSS, TypeScript, React et Java</strong></li>
                <li>Expérience pratique acquise lors d'un stage en développement web chez S2E Groupe</li>
                <li>Intérêt marqué pour la <strong>cybersécurité</strong> (participation à des CTF, formé à l'École 42)</li>
                <li>Curiosité, autonomie et capacité d'adaptation rapide à de nouveaux environnements</li>
              </ul>
            </p>

            <p>
              Vous pouvez consulter mes réalisations sur <a href="https://elijahlasserre.netlify.app" target="_blank">mon portfolio</a>,
              et trouverez mon <strong>CV</strong> et une <strong>lettre de motivation personnalisée</strong> en pièces jointes.
            </p>

            <p>
              Seriez-vous disponible pour un court échange de 15 minutes afin de discuter de la façon dont je pourrais contribuer à vos projets ?
            </p>

            <div class="signature">
              <p>
                Cordialement,<br /><br />
                <strong>Elijah Lasserre</strong><br />
                📧 <a href="mailto:elijahlasserre63@gmail.com">elijahlasserre63@gmail.com</a><br />
                📱 06 18 47 62 31
              </p>
            </div>
          </body>
        </html>
        """
        
        msg.attach(MIMEText(html_content, 'html'))
        
        temp_pdf_path = creer_lettre_motivation_pdf(contenu, nom_entreprise)
        
        if temp_pdf_path:
            with open(temp_pdf_path, 'rb') as f:
                lettre_piece = MIMEApplication(f.read(), Name=f"Lettre_Motivation_{NOM_CANDIDAT.replace(' ', '_')}.pdf")
                lettre_piece['Content-Disposition'] = f'attachment; filename="Lettre_Motivation_{NOM_CANDIDAT.replace(" ", "_")}.pdf"'
                msg.attach(lettre_piece)
            logging.info(f"Lettre de motivation ajoutée comme pièce jointe pour {destinataire}")
        
        if not os.path.exists(chemin_cv):
            logging.warning(f"Le CV {chemin_cv} n'existe pas. L'email sera envoyé sans cette pièce jointe.")
        else:
            with open(chemin_cv, 'rb') as f:
                cv_piece = MIMEApplication(f.read(), Name=os.path.basename(chemin_cv))
            
            cv_piece['Content-Disposition'] = f'attachment; filename="{os.path.basename(chemin_cv)}"'
            msg.attach(cv_piece)
            logging.info(f"CV {chemin_cv} ajouté comme pièce jointe pour {destinataire}")
        
        serveur = smtplib.SMTP(serveur_smtp, port)
        serveur.starttls()
        serveur.login(expediteur, mot_de_passe)
        serveur.send_message(msg)
        serveur.quit()
        
        # Enregistrer l'email comme envoyé
        enregistrer_email_envoye(destinataire, nom_entreprise)
        
        logging.info(f"Email envoyé avec succès à {destinataire}")
        return True
    except Exception as e:
        logging.error(f"Erreur lors de l'envoi à {destinataire}: {e}")
        return False
    finally:
        if temp_pdf_path and os.path.exists(temp_pdf_path):
            try:
                os.remove(temp_pdf_path)
            except Exception as e:
                logging.error(f"Erreur lors de la suppression du fichier temporaire: {e}")

def process_csv_and_send_emails(input_file, expediteur, mot_de_passe, chemin_cv=CHEMIN_CV, dry_run=False, multithreading=False, max_threads=5, cache_lettres=True):
    """
    Lit le fichier CSV et pour chaque ligne, génère une lettre de motivation personnalisée 
    et l'envoie à l'adresse email correspondante avec le CV en pièce jointe.
    
    Args:
        input_file: Chemin vers le fichier CSV contenant les emails
        expediteur: Adresse email de l'expéditeur
        mot_de_passe: Mot de passe de l'expéditeur
        chemin_cv: Chemin vers le CV à joindre
        dry_run: Mode test (n'envoie pas réellement les emails)
        multithreading: Utiliser le multithreading pour envoyer les emails en parallèle
        max_threads: Nombre maximum de threads en parallèle
        cache_lettres: Mettre en cache les lettres de motivation par catégorie
    """
    import threading
    from queue import Queue
    
    rows_processed = 0
    emails_found = 0
    emails_sent = 0
    emails_skipped = 0
    
    # Cache pour les lettres de motivation par catégorie
    lettres_cache = {}
    
    # Limiter le nombre de requêtes API consécutives
    api_calls_count = 0
    api_calls_limit = 10  # Nombre maximum d'appels API consécutifs avant pause
    api_calls_pause = 30  # Pause en secondes après avoir atteint la limite
    
    if not os.path.exists(chemin_cv):
        logging.warning(f"Le CV {chemin_cv} n'existe pas. Assurez-vous de spécifier le bon chemin.")
        confirmation = input("Voulez-vous continuer sans CV en pièce jointe? (o/n): ")
        if confirmation.lower() != 'o':
            logging.info("Opération annulée par l'utilisateur.")
            return
    
    # Fonction pour traiter un email (utilisée en mode multithreading)
    def traiter_email(task):
        nonlocal emails_sent, emails_skipped, api_calls_count
        
        email, entreprise_info, nom_entreprise = task
        
        # Vérifier si l'email a déjà été envoyé
        if verifier_email_deja_envoye(email, nom_entreprise):
            logging.info(f"Email déjà envoyé à {nom_entreprise} ({email}) - Ligne ignorée")
            emails_skipped += 1
            return
        
        # Gestion de la limite d'appels API
        if not cache_lettres or not any(entreprise_info.get('category', '') == cat for cat in lettres_cache):
            api_calls_count += 1
            if api_calls_count >= api_calls_limit:
                api_calls_count = 0
                logging.info(f"Limite d'appels API atteinte. Pause de {api_calls_pause} secondes...")
                time.sleep(api_calls_pause)
        
        # Utiliser le cache si possible
        categorie = entreprise_info.get('category', '')
        cache_key = categorie if cache_lettres else None
        
        if cache_key and cache_key in lettres_cache:
            contenu_lettre = lettres_cache[cache_key]
            # Personnalisation minimale pour adapter la lettre en cache
            contenu_lettre = contenu_lettre.replace("[NOM_ENTREPRISE]", nom_entreprise)
        else:
            contenu_lettre = generer_lettre_motivation(entreprise_info)
            if cache_key:
                # Stocker dans le cache avec des marqueurs pour personnalisation future
                lettres_cache[cache_key] = contenu_lettre.replace(nom_entreprise, "[NOM_ENTREPRISE]")
        
        objet_email = f"Candidature pour un stage en développement - {NOM_CANDIDAT} - {nom_entreprise}"
        
        if dry_run:
            logging.info(f"[MODE TEST] Email simulé pour {email}")
            # Même en mode test, on enregistre l'email comme "envoyé" pour éviter les doublons
            enregistrer_email_envoye(email, nom_entreprise)
            emails_sent += 1
        else:
            # Délai réduit entre les emails
            time.sleep(random.uniform(EMAIL_CONFIG['delay_min'], EMAIL_CONFIG['delay_max']))
            
            if envoyer_email_avec_cv(email, objet_email, contenu_lettre, expediteur, mot_de_passe, 
                                   chemin_cv, nom_entreprise, EMAIL_CONFIG['smtp_server'], 
                                   EMAIL_CONFIG['smtp_port'], entreprise_info):
                emails_sent += 1
    
    try:
        # Lecture complète du CSV d'abord pour préparer les tâches
        tasks = []
        with open(input_file, 'r', encoding='utf-8') as csv_in:
            reader = csv.DictReader(csv_in)
            for row in reader:
                rows_processed += 1
                email = row.get('email', '')
                
                if email and '@' in email:
                    email = email.strip()
                    if "sentry" in email.lower():
                        logging.info(f"Email {email} ignoré (contient 'sentry')")
                        continue
                    
                    emails_found += 1
                    
                    entreprise_info = {
                        'title': row.get('title', ''),
                        'category': row.get('category', ''),
                        'city': row.get('city', ''),
                        'country': row.get('country', ''),
                        'website': row.get('website', ''),
                        'phone': row.get('phone', '')
                    }
                    
                    nom_entreprise = entreprise_info['title']
                    logging.info(f"Préparation de {nom_entreprise} ({email})")
                    
                    # Ajouter à la liste des tâches à traiter
                    tasks.append((email, entreprise_info, nom_entreprise))
                else:
                    logging.warning(f"Aucun email valide trouvé dans la ligne {rows_processed}")
        
        # Mode multithreading
        if multithreading and len(tasks) > 0:
            logging.info(f"Utilisation du multithreading avec {min(max_threads, len(tasks))} threads")
            
            # Créer une file d'attente et la remplir avec les tâches
            task_queue = Queue()
            for task in tasks:
                task_queue.put(task)
            
            # Fonction pour les workers
            def worker():
                while not task_queue.empty():
                    try:
                        task = task_queue.get(block=False)
                        traiter_email(task)
                        task_queue.task_done()
                    except Exception as e:
                        logging.error(f"Erreur dans le thread: {e}")
                    
            # Créer et démarrer les threads
            threads = []
            for _ in range(min(max_threads, len(tasks))):
                t = threading.Thread(target=worker)
                t.daemon = True
                threads.append(t)
                t.start()
            
            # Attendre que tous les threads terminent
            for t in threads:
                t.join()
                
        else:
            # Mode séquentiel
            for task in tasks:
                traiter_email(task)
        
        logging.info(f"Traitement terminé : {rows_processed} lignes lues, {emails_found} emails trouvés, {emails_sent} emails envoyés, {emails_skipped} emails ignorés (déjà envoyés).")
    
    except FileNotFoundError:
        logging.error(f"Fichier {input_file} introuvable.")
    except Exception as e:
        logging.error(f"Erreur lors du traitement du fichier CSV : {e}")
        import traceback
        logging.error(traceback.format_exc())

def parse_arguments():
    """Parse les arguments de ligne de commande."""
    parser = argparse.ArgumentParser(description='Outil d\'envoi automatisé d\'emails de candidature')
    
    parser.add_argument('input_file', help='Fichier CSV contenant les emails cibles')
    parser.add_argument('--sender', '-s', dest='expediteur', help='Email expéditeur')
    parser.add_argument('--password', '-p', dest='mot_de_passe', help='Mot de passe expéditeur')
    parser.add_argument('--cv', '-c', dest='chemin_cv', help='Chemin vers le CV')
    parser.add_argument('--dry-run', '-d', action='store_true', help='Mode test (n\'envoie pas réellement les emails)')
    parser.add_argument('--multithreading', '-m', action='store_true', help='Activer le multithreading')
    parser.add_argument('--threads', '-t', type=int, default=5, help='Nombre de threads (défaut: 5)')
    parser.add_argument('--no-cache', '-n', action='store_true', help='Désactiver le cache de lettres')
    
    return parser.parse_args()

if __name__ == "__main__":
    # Vérifier si le fichier .env existe, sinon en créer un modèle
    if not os.path.exists('.env'):
        with open('.env', 'w') as f:
            f.write("""# Informations personnelles
NOM_CANDIDAT=Votre Nom
SIGNATURE=

Cordialement,
Votre Nom
Tél: Votre numéro
Email: votre@email.com

# Chemin vers les fichiers
CHEMIN_CV=votre_cv.pdf

# Configuration API
MISTRAL_API_KEY=votre_clé_api_mistral

# Configuration email
EMAIL_SMTP_SERVER=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_DELAY_MIN=5
EMAIL_DELAY_MAX=15
""")
        print("Un fichier .env a été créé. Veuillez le configurer avec vos informations avant de continuer.")
        sys.exit(0)
    
    # Vérifier si la clé API Mistral est configurée
    if not MISTRAL_API_KEY:
        print("Erreur: La clé API Mistral n'est pas configurée. Veuillez la définir dans le fichier .env")
        sys.exit(1)
    
    args = parse_arguments()
    
    # Utiliser les arguments ou les variables d'environnement
    expediteur = args.expediteur or os.getenv('EMAIL_EXPEDITEUR')
    mot_de_passe = args.mot_de_passe or os.getenv('EMAIL_MOT_DE_PASSE')
    chemin_cv = args.chemin_cv or CHEMIN_CV
    
    if not expediteur or not mot_de_passe:
        print("Erreur: L'email expéditeur et le mot de passe sont requis.")
        print("Vous pouvez les définir dans le fichier .env ou les passer en arguments:")
        print(f"python {sys.argv[0]} input_file.csv --sender votre@email.com --password votre_mot_de_passe")
        sys.exit(1)
    
    process_csv_and_send_emails(
        args.input_file, 
        expediteur, 
        mot_de_passe, 
        chemin_cv, 
        args.dry_run, 
        args.multithreading, 
        args.threads, 
        not args.no_cache
    )