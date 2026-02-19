
document.getElementById('themeToggle')?.addEventListener('click',()=>{const c=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=c;localStorage.setItem('theme',c)});
