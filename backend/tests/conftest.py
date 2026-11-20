import os,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('JWT_SECRET','test-secret')
os.environ.setdefault('DATABASE_URL','sqlite:///'+tempfile.mkdtemp(prefix='km-test-')+'/test.db')
