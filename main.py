from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import requests
import re
import time
import pandas as pd
import os
import tempfile
import uuid
from typing import List
import asyncio

app = FastAPI(title="NCBI Sequences Extractor", version="1.0.0")

# Configuración CORS para permitir el cliente HTML
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, especifica los dominios permitidos
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def extract_cds_translation_genbank(genbank_content):
    """
    Extrae la secuencia de traducción del contenido GenBank completo
    con un patrón más robusto para el formato GenBank
    """
    pattern = r'CDS\s+.*?/translation="([^"]*)"'
    
    match = re.search(pattern, genbank_content, re.DOTALL | re.IGNORECASE)
    
    if match:
        raw_sequence = match.group(1)
        clean_sequence = re.sub(r'\s+', '', raw_sequence)
        return clean_sequence
    
    return None

def get_genbank_content(accession):
    """
    Obtiene el contenido GenBank completo usando el formato text de NCBI
    """
    url = f"https://www.ncbi.nlm.nih.gov/sviewer/viewer.fcgi?id={accession}&db=nuccore&report=genbank&retmode=text"
    
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.text
    except Exception as e:
        print(f"Error obteniendo GenBank para {accession}: {str(e)}")
        return None

async def scrape_ncbi_sequences(accession_list):
    """
    Función principal para scrapear secuencias de NCBI usando formato GenBank
    """
    results = []
    
    for accession in accession_list:
        print(f"Procesando: {accession}")
        
        try:
            # Obtener contenido GenBank completo
            genbank_content = get_genbank_content(accession)
            
            if genbank_content:
                sequence = extract_cds_translation_genbank(genbank_content)
                
                if sequence:
                    results.append({
                        'ID': f">{accession}",
                        'SEQUENCE': sequence,
                        'estado': 'éxito'
                    })
                    print(f"✓ Secuencia encontrada para {accession}")
                    print(f"  Longitud: {len(sequence)} aminoácidos")
                    print(f"  Primeros 50: {sequence[:50]}")
                else:
                    results.append({
                        'ID': f">{accession}",
                        'SEQUENCE': 'No encontrada en GenBank',
                        'estado': 'secuencia no encontrada'
                    })
                    print(f"✗ Secuencia NO encontrada para {accession}")
            else:
                results.append({
                    'ID': f">{accession}",
                    'SEQUENCE': 'Error obteniendo GenBank',
                    'estado': 'error'
                })
                print(f"✗ Error obteniendo GenBank para {accession}")
                
        except Exception as e:
            results.append({
                'ID': f">{accession}",
                'SEQUENCE': f'Error: {str(e)}',
                'estado': 'error'
            })
            print(f"✗ Error general para {accession}: {str(e)}")
        
        # Pequeña pausa para ser amable con el servidor
        await asyncio.sleep(1)
    
    return results

def leer_accesiones_desde_contenido(contenido: str):
    """
    Lee accesiones desde el contenido de texto y las divide por comas
    """
    accesiones = []
    try:
        contenido = contenido.strip()
        if contenido:
            accesiones = [acc.strip() for acc in contenido.split(',') if acc.strip()]
        return accesiones
    except Exception as e:
        print(f"Error al procesar el contenido: {e}")
        return []

@app.post("/api/extract-sequences")
async def extract_sequences(file: UploadFile = File(...)):
    """
    Endpoint para procesar un archivo TXT con accesiones y devolver un CSV con las secuencias
    """
    # Verificar que es un archivo TXT
    if not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="Solo se permiten archivos .txt")
    
    try:
        # Leer el contenido del archivo
        content = await file.read()
        contenido_texto = content.decode('utf-8')
        
        # Leer las accesiones del contenido
        accesiones = leer_accesiones_desde_contenido(contenido_texto)
        
        if not accesiones:
            raise HTTPException(status_code=400, detail="No se pudieron leer las accesiones del archivo")
        
        # Procesar las secuencias
        resultados = await scrape_ncbi_sequences(accesiones)
        
        # Crear archivo temporal para el CSV
        unique_id = str(uuid.uuid4())[:8]
        temp_output = os.path.join(tempfile.gettempdir(), f"secuencias_{unique_id}.csv")
        
        # Crear DataFrame y guardar resultados
        df = pd.DataFrame(resultados)
        df.to_csv(temp_output, index=False, encoding='utf-8')
        
        # Contar resultados
        exitos = len([r for r in resultados if r['estado'] == 'éxito'])
        
        # Devolver el archivo CSV
        return FileResponse(
            path=temp_output,
            filename=f"secuencias_{unique_id}.csv",
            media_type='text/csv',
            headers={'Content-Disposition': f'attachment; filename=secuencias_{unique_id}.csv'}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error en el procesamiento: {str(e)}")

@app.get("/api/health")
async def health_check():
    """Endpoint para verificar que el servicio está funcionando"""
    return {
        "status": "ok", 
        "message": "Servicio de extracción de secuencias funcionando",
        "version": "1.0.0"
    }

@app.get("/")
async def root():
    """Endpoint raíz con información del API"""
    return {
        "message": "NCBI Sequences Extractor API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/api/health",
            "extract_sequences": "/api/extract-sequences (POST)"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)