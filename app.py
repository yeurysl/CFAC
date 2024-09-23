from flask import Flask
from flask import Flask, render_template


app = Flask(__name__)

@app.route('/base')
def base():
    return render_template('/base.html')

@app.route('/')
def home():
    return render_template('/home.html')

@app.route('/aboutus')
def about():
    return render_template('/aboutus.html')

@app.route('/header')
def header():
    return render_template('/header.html')

if __name__ == '__main__':
    app.run(debug=True)
