
const form=document.getElementById('postForm');
const editor=document.getElementById('editor');
const contentInput=document.getElementById('contentInput');
const titleInput=form?.querySelector('input[name="title"]');
const slugInput=form?.querySelector('input[name="slug"]');
const excerptInput=form?.querySelector('textarea[name="excerpt"]');
const seoTips=document.getElementById('seoTips');
const featured=document.getElementById('featuredImage');
const hiddenImage=form?.querySelector('input[name="featured_image"]');

if(form){
  titleInput?.addEventListener('input',()=>{ if(!slugInput.value){ slugInput.value=titleInput.value.toLowerCase().normalize('NFD').replace(/[^\w\s-]/g,'').replace(/\s+/g,'-'); }});
  form.addEventListener('submit',()=>{contentInput.value=editor.innerHTML; if(!excerptInput.value){excerptInput.value=editor.innerText.slice(0,160);} });
  const suggest=()=>{const txt=editor.innerText; const words=txt.split(/\s+/).filter(Boolean); const heads=editor.querySelectorAll('h2').length; let msg=`Palabras: ${words.length}. `; if(heads<2) msg+='Añade más H2 para SEO. '; if(!editor.querySelector('h1')) msg+='Falta H1. '; msg+='Sugerencia enlaces internos: /category/diario-de-aprendizaje'; seoTips.innerText=msg;};
  editor.addEventListener('input', suggest); suggest();
  document.getElementById('autosave')?.addEventListener('click',()=>{contentInput.value=editor.innerHTML; localStorage.setItem('draft_'+(slugInput.value||'new'), JSON.stringify(Object.fromEntries(new FormData(form)))); alert('Borrador guardado en navegador');});
  const key='draft_'+(slugInput.value||'new'); const draft=localStorage.getItem(key); if(draft && !form.querySelector('input[name="id"]').value){const d=JSON.parse(draft); for(const [k,v] of Object.entries(d)){const el=form.querySelector(`[name="${k}"]`); if(el) el.value=v;} if(d.content) editor.innerHTML=d.content;}
  featured?.addEventListener('change', async (e)=>{const file=e.target.files[0]; if(!file) return; const img=await createImageBitmap(file); const canvas=document.createElement('canvas'); canvas.width=img.width; canvas.height=img.height; const ctx=canvas.getContext('2d'); ctx.drawImage(img,0,0); canvas.toBlob(async(blob)=>{const seoName=(slugInput.value||titleInput.value||'image').toLowerCase().replace(/\s+/g,'-')+'.webp'; const res=await fetch('/admin/upload-image',{method:'POST',headers:{'X-File-Name':seoName},body:blob}); const j=await res.json(); hiddenImage.value=j.filename; const alt=form.querySelector('input[name="featured_image_alt"]'); if(!alt.value){alt.value='Imagen destacada: '+(titleInput.value||'aprendizaje de chino');} }, 'image/webp', 0.8);
  });
}
