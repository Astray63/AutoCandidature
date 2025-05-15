#!/usr/bin/env python3
import csv
import json
import sys
import re

def clean_json_string(json_str):
    """Nettoie une chaîne JSON pour qu'elle soit correctement analysable"""
    if not json_str:
        return json_str
    # Remplacer les doubles quotes échappées
    json_str = json_str.replace('\\"', '"')
    # S'assurer que les guillemets externes sont simples
    if json_str.startswith('"') and json_str.endswith('"'):
        json_str = json_str[1:-1]
    return json_str

def is_valid_email(email):
    """
    Vérifie si une chaîne est un email valide.
    Rejette les extensions d'images et les formats invalides.
    """
    if not email or len(email) < 5:  # Un email valide a au moins 5 caractères (a@b.c)
        return False
    
    # Décodage URL (convertir %20 en espace, etc.)
    if '%' in email:
        import urllib.parse
        email = urllib.parse.unquote(email)
    
    # Supprimer les espaces au début, à la fin et dans l'email
    email = email.strip().replace(' ', '')
    
    # Rejeter les chaînes qui ressemblent à des chemins de fichiers d'images
    invalid_extensions = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.webp', '.svg', '.ico']
    for ext in invalid_extensions:
        if email.lower().endswith(ext):
            return False
    
    # Vérifier que l'adresse a un format valide
    # Plus strict que le regex précédent
    email_pattern = r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$'
    if not re.match(email_pattern, email):
        return False
    
    # Vérifications supplémentaires
    # - Au moins un caractère avant @
    # - Au moins un caractère entre @ et .
    # - Au moins deux caractères après le dernier .
    parts = email.split('@')
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return False
    
    domain_parts = parts[1].split('.')
    if len(domain_parts) < 2 or not domain_parts[-1] or len(domain_parts[-1]) < 2:
        return False
    
    # Vérifier que le TLD n'est pas un nombre
    if domain_parts[-1].isdigit():
        return False
    
    # Rejeter les exemples d'emails génériques
    generic_emails = [
        'example@', 'exemple@', 'sample@', 'test@', 'demo@',
        '@example.', '@exemple.', '@sample.', '@test.', '@demo.',
        'john.doe@', 'jane.doe@', 'user@', 'info@example', 'contact@example'
    ]
    
    email_lower = email.lower()
    for generic in generic_emails:
        if generic in email_lower:
            return False
    
    return True

def clean_email(email):
    """
    Nettoie une adresse email en supprimant les caractères URL-encodés et les espaces.
    """
    if not email:
        return email
        
    # Décodage URL
    if '%' in email:
        import urllib.parse
        email = urllib.parse.unquote(email)
    
    # Supprimer les espaces
    return email.strip().replace(' ', '')

def improve_csv(input_file, output_file="improved_emails.csv"):
    try:
        rows_processed = 0
        emails_found = 0
        emails_rejected = 0
        with open(input_file, 'r', encoding='utf-8') as csv_in:
            reader = csv.DictReader(csv_in)

            # Définir les nouveaux champs pour le fichier de sortie
            fieldnames = [
                'email', 'title', 'category',
                'owner_id', 'owner_name',
                'street', 'city', 'postal_code', 'country',
                'has_wheelchair_accessible_parking',
                'address', 'website', 'phone', 'link', 'clean_link'
            ]

            with open(output_file, 'w', encoding='utf-8', newline='') as csv_out:
                writer = csv.DictWriter(csv_out, fieldnames=fieldnames)
                writer.writeheader()

                # Suivi des emails déjà traités pour éviter les doublons
                processed_emails = set()

                for row in reader:
                    rows_processed += 1

                    # Extraire les emails de la colonne 'emails'
                    emails_str = row.get('emails', '')
                    if emails_str:
                        # Extraire tous les emails avec une regex plus permissive pour la capture initiale
                        email_pattern = r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z0-9]{2,}'
                        potential_emails = re.findall(email_pattern, emails_str)

                        # Traiter chaque email trouvé avec une validation plus stricte
                        if potential_emails:
                            for email in potential_emails:
                                # Nettoyer l'email (supprimer les encodages URL, espaces, etc.)
                                email = clean_email(email)
                                
                                # Vérifier si l'email est valide, n'est pas un doublon et ne contient pas "sentry"
                                if not is_valid_email(email) or "sentry" in email.lower() or email.lower() in processed_emails:
                                    emails_rejected += 1
                                    continue

                                emails_found += 1
                                processed_emails.add(email.lower())  # Ajouter aux emails traités

                                # Créer une nouvelle ligne pour chaque email
                                new_row = {
                                    'email': email,
                                    'title': row.get('title', ''),
                                    'category': row.get('category', ''),
                                    'address': row.get('address', ''),
                                    'website': row.get('website', ''),
                                    'phone': row.get('phone', ''),
                                    'link': row.get('link', '')
                                }

                                # Extraire un lien propre sans les paramètres
                                clean_link = row.get('link', '')
                                if clean_link:
                                    # Supprimer tout après le premier ? ou #
                                    clean_link = re.sub(r'[?#].*$', '', clean_link)
                                new_row['clean_link'] = clean_link

                                # Traiter la colonne owner (JSON)
                                try:
                                    if row.get('owner'):
                                        owner_str = clean_json_string(row['owner'])
                                        owner_data = json.loads(owner_str)
                                        new_row['owner_id'] = owner_data.get('id', '')
                                        new_row['owner_name'] = owner_data.get('name', '').replace(' (propriétaire)', '')
                                    else:
                                        new_row['owner_id'] = ''
                                        new_row['owner_name'] = ''
                                except (json.JSONDecodeError, TypeError) as e:
                                    if rows_processed <= 2:  # Limiter les erreurs affichées
                                        print(f"Erreur lors du décodage de owner à la ligne {rows_processed}: {e}")
                                    new_row['owner_id'] = ''
                                    new_row['owner_name'] = ''

                                # Traiter la colonne complete_address (JSON)
                                try:
                                    if row.get('complete_address'):
                                        address_str = clean_json_string(row['complete_address'])
                                        address_data = json.loads(address_str)
                                        new_row['street'] = address_data.get('street', '')
                                        new_row['city'] = address_data.get('city', '')
                                        new_row['postal_code'] = address_data.get('postal_code', '')
                                        new_row['country'] = address_data.get('country', '')
                                    else:
                                        new_row['street'] = ''
                                        new_row['city'] = ''
                                        new_row['postal_code'] = ''
                                        new_row['country'] = ''
                                except (json.JSONDecodeError, TypeError) as e:
                                    if rows_processed <= 2:
                                        print(f"Erreur lors du décodage de complete_address à la ligne {rows_processed}: {e}")
                                    new_row['street'] = ''
                                    new_row['city'] = ''
                                    new_row['postal_code'] = ''
                                    new_row['country'] = ''

                                # Traiter la colonne about (JSON - liste d'attributs)
                                has_wheelchair = 'Non'
                                try:
                                    about_str = row.get('about', '')
                                    if about_str and about_str.lower() != 'null' and about_str != '':
                                        about_str = clean_json_string(about_str)
                                        about_data = json.loads(about_str)

                                        # Vérifier si about_data est bien une liste
                                        if about_data and isinstance(about_data, list):
                                            # Chercher l'accessibilité en fauteuil roulant
                                            for item in about_data:
                                                if isinstance(item, dict) and item.get('id') == 'accessibility':
                                                    for option in item.get('options', []):
                                                        if option.get('name') == 'Parking accessible en fauteuil roulant' and option.get('enabled') == True:
                                                            has_wheelchair = 'Oui'
                                                            break
                                except (json.JSONDecodeError, TypeError):
                                    # Ignorer les erreurs pour about
                                    pass

                                new_row['has_wheelchair_accessible_parking'] = has_wheelchair

                                # Écrire la ligne dans le fichier de sortie
                                writer.writerow(new_row)
                        else:
                            if rows_processed <= 5:
                                print(f"Aucun email trouvé à la ligne {rows_processed}")
                    else:
                        if rows_processed <= 5:
                            print(f"Colonne 'emails' vide à la ligne {rows_processed}")

        print(f"Amélioration terminée. {rows_processed} lignes traitées, {emails_found} emails extraits, {emails_rejected} emails rejetés.")
        print(f"Résultat enregistré dans {output_file}")
        return True

    except FileNotFoundError:
        print(f"Erreur: Fichier {input_file} introuvable.")
        return False
    except Exception as e:
        print(f"Erreur: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Vérifier les arguments
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input_file.csv> [output_file.csv]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "improved_emails.csv"

    if not improve_csv(input_file, output_file):
        sys.exit(2)
