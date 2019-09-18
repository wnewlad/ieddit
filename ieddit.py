from flask import Flask, render_template, session, request, redirect
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func

from werkzeug.security import generate_password_hash, check_password_hash
import re
import config

from models import *
from functions import *

app = Flask(__name__)
app.config.from_object('config')

db = SQLAlchemy(app)

@app.route('/')
def index():
	return subi('all')
	
@app.route('/login',  methods=['GET', 'POST'])
def login():
	if request.method == 'GET':
		return render_template('login.html')
	if request.method == 'POST':
		username = request.form.get('username')
		password = request.form.get('password')
		if username == None or password == None or len(username) > 20 or len(password) > 100:
			return 'invalid login'

		if db.session.query(db.session.query(Iuser)
				.filter_by(username=username)
				.exists()).scalar():
			login_user = db.session.query(Iuser).filter_by(username=username).first()
			hashed_pw = login_user.password
			if check_password_hash(hashed_pw, password):
				session['username'] = login_user.username
				session['user_id'] = login_user.id
				return redirect(config.URL, 302)

		return 'login failed' 

@app.route('/register', methods=['POST'])
def register():
	if request.method == 'POST':
		username = request.form.get('username')
		password = request.form.get('password')
		email = request.form.get('email')

		if verify_username(username):
			if db.session.query(db.session.query(Iuser)
				.filter_by(username=username).exists()).scalar():
				return 'exists'
		else:
			return 'invalid username'

		if len(password) > 100:
			return 'pass to long'

		if email != '':
			if not re.match(r'[^@]+@[^@]+\.[^@]+', email):
				return 'invalid email'

		new_user = Iuser(username=username, email=email,
			password=generate_password_hash(password))
		db.session.add(new_user)
		db.session.commit()
		session['username'] = new_user.username
		session['user_id'] = new_user.id
		return redirect(config.URL, 302)

# These two functions look the same, but they will work somewhat different in fucture
@app.route('/r/<subi>/')
def subi(subi):
	if subi != 'all':
		if verify_subname(subi) == False:
			return 'invalid subpath'
		subname = db.session.query(Sub).filter(func.lower(Sub.name) == subi.lower()).first()

		if subname == None:
			return 'invalid sub'
		posts = db.session.query(Post).filter_by(sub=subi).all()
	else:
		posts = db.session.query(Post).all()
	p = []
	for post in posts:
		post.created_ago = time_ago(post.created)
		if subi != 'all':
			post.site_url = config.URL + '/r/' + subi + '/' + str(post.id) + '/' + post.inurl_title
		post.remote_url_parsed = post_url_parse(post.url)
		post.comment_count = db.session.query(Comment).filter_by(post_id=post.id).count()
		if 'user_id' in session:
			post.has_voted = db.session.query(Vote).filter_by(post_id=post.id, user_id=session['user_id']).first()
			if post.has_voted != None:
				post.has_voted = post.has_voted.vote
		p.append(post)

	return render_template('sub.html', posts=p, url=config.URL)

@app.route('/r/<sub>/<post_id>/<inurl_title>/<comment_id>/sort-<sort_by>')
@app.route('/r/<sub>/<post_id>/<inurl_title>/<comment_id>/')
@app.route('/r/<sub>/<post_id>/<inurl_title>/sort-<sort_by>')
@app.route('/r/<sub>/<post_id>/<inurl_title>/')
def comment(sub, post_id, inurl_title, comment_id=False, sort_by=None):
	if sub == None or post_id == None or inurl_title == None:
		return 'badlink'
	try:
		int(comment_id)
	except:
		comment_id = False
	post = db.session.query(Post).filter_by(id=post_id, sub=sub).first()
	post.comment_count = db.session.query(Comment).filter_by(post_id=post.id).count()
	post.created_ago = time_ago(post.created)
	post.remote_url_parsed = post_url_parse(post.url)
	if 'user_id' in session:
		post.has_voted = db.session.query(Vote).filter_by(post_id=post.id, user_id=session['user_id']).first()
		if post.has_voted != None:
			post.has_voted = post.has_voted.vote

	if not comment_id:
		if sort_by == 'new':
			comments = db.session.query(Comment).filter(Comment.post_id == post_id, Comment.level < 7)\
			.order_by((Comment.created).asc()).all()

		#if sort_by == None or sort_by == 'top':
		else:
			comments = db.session.query(Comment).filter(Comment.post_id == post_id, Comment.level < 7)\
			.order_by((Comment.ups - Comment.downs).desc()).all()

		parent_comment = None
		parent_posturl = None
	else:
		comments = list_of_child_comments(comment_id, sort_by=sort_by)
		parent_comment = db.session.query(Comment).filter_by(id=comment_id).first()
		comments.append(parent_comment)

	for c in comments:
		c.created_ago = time_ago(c.created)
		if 'user_id' in session:
			c.has_voted = db.session.query(Vote).filter_by(comment_id=c.id, user_id=session['user_id']).first()
			if c.has_voted != None:
				c.has_voted = c.has_voted.vote

	if not comment_id:
		tree = create_id_tree(comments)
	else:
		tree = create_id_tree(comments, parent_id=comment_id)

	tree = comment_structure(comments, tree)
	return render_template('comments.html', comments=comments, post_id=post_id, 
		post_url='%s/r/%s/%s/%s/' % (config.URL, sub, post_id, post.inurl_title), 
		post=post, tree=tree, parent_comment=parent_comment)

# need to entirely rewrite how comments are handled once everything else is complete
# this sort of recursion KILLS performance, especially when combined with the already
# terrible comment_structure function. only reason i'm doing it this way now is
# performance doens't matter and i don't have redis/similar setup yet
def list_of_child_comments(comment_id, sort_by=None):
	comments = {}
	current_comments = []
	if sort_by == 'new':
		start = db.session.query(Comment).filter(Comment.parent_id == comment_id)\
					.order_by((Comment.created).asc()).all()
	else:
		start = db.session.query(Comment).filter(Comment.parent_id == comment_id)\
					.order_by((Comment.ups - Comment.downs).desc()).all()

	for c in start:
		current_comments.append(c.id)
		comments[c.id] = c
	while len(current_comments) > 0:
		for current_c in current_comments:
			if sort_by == 'new':
				get_comments = db.session.query(Comment).filter(Comment.parent_id == current_c)\
					.order_by((Comment.created).asc()).all()
			else:
				get_comments = db.session.query(Comment).filter(Comment.parent_id == current_c)\
					.order_by((Comment.ups - Comment.downs).desc()).all()
			for c in get_comments:
				current_comments.append(c.id)
				comments[c.id] = c
			current_comments.remove(current_c)
	return [comments[c] for c in comments]

@app.route('/create', methods=['POST', 'GET'])
def create_sub():
	if request.method == 'POST':
		subname = request.form.get('subname')
		if subname != None and verify_subname(subname) and 'username' in session:
			if len(subname) > 30 or len(subname) < 1:
				return 'invalid length'
			new_sub = Sub(name=subname, created_by=session['username'])
			db.session.add(new_sub)
			db.session.commit()
			return redirect(config.URL + '/r/' + subname, 302)
		return 'invalid'
	elif request.method == 'GET':
		return render_template('create.html')

@app.route('/u/<uname>/', methods=['GET'])
def view_user(uname):
	return render_template('user.html', user=uname);

@app.route('/vote', methods=['GET', 'POST'])
def vote():
	if request.method == 'POST':
		post_id = request.form.get('post_id')
		comment_id = request.form.get('comment_id')
		vote = request.form.get('vote')
		user_id = session['user_id']
	
		if 'username' not in session:
			return 'not logged in'
		if comment_id != None and post_id != None:
			return 'cannot vote for 2 objects'
		if comment_id == None and post_id == None:
			return 'no vote object'
		if vote not in ['1', '-1', '0']:
			return 'invalid vote amount'
	
		vote = int(vote)

		invert_vote = False
		if post_id != None:
			last_vote = db.session.query(Vote).filter_by(user_id=user_id, post_id=post_id).first()
			if last_vote != None:
				if last_vote.vote == vote:
					return 'already voted'
				else:
					invert_vote = True

		elif comment_id != None:
			last_vote = db.session.query(Vote).filter_by(user_id=user_id, comment_id=comment_id).first()
			if last_vote != None:
				if last_vote.vote == vote:
					return 'already voted'
				else:
					invert_vote = True

		if vote == 0 and last_vote == None:
			return 'never voted'

		if vote == 0:
			if last_vote.post_id != None:
				if last_vote.post_id != None:
					vpost = db.session.query(Post).filter_by(id=last_vote.post_id).first()
				elif last_vote.comment_id != None:
					vpost = db.session.query(Comment).filter_by(id=last_vote.post_id).first()
				if last_vote.vote == 1:
					vpost.ups -= 1
				elif last_vote.vote == -1:
					vpost.downs -= 1
			db.session.delete(last_vote)
			db.session.commit()
			return str(vpost.ups - vpost.downs)

		if last_vote == None:
			new_vote = Vote(user_id=user_id, vote=vote, comment_id=comment_id, post_id=post_id)
			db.session.add(new_vote)
			db.session.commit()

		elif invert_vote:
			if last_vote.vote == 1:
				last_vote.vote = -1
			else:
				last_vote.vote = 1
		db.session.commit()

		if comment_id != None:
			vcom = db.session.query(Comment).filter_by(id=comment_id).first()
		elif post_id != None:
			vcom = db.session.query(Post).filter_by(id=post_id).first()


		if vote == 1:
			if not invert_vote:
				vcom.ups += 1
			else:
				vcom.ups += 1
				vcom.downs -= 1

		elif vote == -1:
			if not invert_vote:
				vcom.downs += 1
			else:
				vcom.downs += 1
				vcom.ups -= 1

		db.session.commit()	

	
		return str(vcom.ups - vcom.downs)
	elif request.method == 'GET':
		return 'get'

@app.route('/create_post', methods=['POST', 'GET'])
def create_post():
	if request.method == 'POST':
		title = request.form.get('title')
		url = request.form.get('url')
		sub = request.form.get('sub')
		if title == None or url == None or 'username' not in session:
			return 'invalid post'
		if len(title) > 400 or len(title) < 1 or len(sub) > 30 or len(sub) < 1 or len(url) > 2000 or len(url) < 1:
			return 'invalid post len'
		new_post = Post(url=url, title=title, inurl_title=convert_ied(title), author=session['username'], sub=sub)
		db.session.add(new_post)
		db.session.commit()
		url = config.URL + '/r/' + sub
		return redirect(url, 302)

	if request.method == 'GET':
		return render_template('create_sub.html')

@app.route('/create_comment', methods=['POST'])
def create_comment():
	text = request.form.get('comment_text')
	post_id = request.form.get('post_id')
	post_url = request.form.get('post_url')
	parent_id = request.form.get('parent_id')
	if parent_id == '':
		parent_id = None
	if text == None or 'username' not in session or post_id == None or post_url == None:
		return 'bad comment'
	if parent_id != None:
		level = (db.session.query(Comment).filter_by(id=parent_id).first().level) + 1
	else:
		level = None
	new_comment = Comment(post_id=post_id, text=text, username=session['username'], parent_id=parent_id, level=level)
	db.session.add(new_comment)
	db.session.commit()
	return redirect(post_url, 302)

@app.route('/logout', methods=['POST', 'GET'])
def logout():
	session.pop('username', None)
	return redirect(config.URL, 302)